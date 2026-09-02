"""Bounded private-network HTTP(S) contact for explicitly owned/authorized ranges.

This module intentionally does not widen ExternalContactClient. Public egress and
private-network reachability remain separate authority lanes while sharing the same
operational style: exact destinations, bounded methods, bounded redirects, and
machine-readable receipts.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping


class PrivateNetworkContactError(RuntimeError):
    """Fail-closed error for private-network contact."""


@dataclass(frozen=True)
class PrivateNetworkPolicy:
    """Explicit authority for a private-network contact lane.

    Safety invariants:
    - disabled unless ``allow_private_network`` is true;
    - exact host allowlist;
    - every resolved address must fall inside an explicitly configured private CIDR;
    - only RFC1918 IPv4 or IPv6 ULA CIDRs are accepted;
    - loopback, link-local, multicast and unspecified addresses are always rejected;
    - read-only methods only;
    - credentials and destructive methods are not part of this lane.
    """

    allow_private_network: bool = False
    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_cidrs: tuple[str, ...] = ()
    allowed_methods: frozenset[str] = field(
        default_factory=lambda: frozenset({"GET", "HEAD", "OPTIONS"})
    )
    allow_http: bool = False
    follow_redirects: bool = False
    max_redirects: int = 2
    timeout_seconds: float = 3.0
    max_response_bytes: int = 256 * 1024

    @classmethod
    def from_targets(
        cls,
        hosts: Iterable[str],
        cidrs: Iterable[str],
        *,
        allow_http: bool = False,
        follow_redirects: bool = False,
    ) -> "PrivateNetworkPolicy":
        normalized_hosts = frozenset(_normalize_host(h) for h in hosts if h and h.strip())
        normalized_cidrs = tuple(str(_validate_private_cidr(c)) for c in cidrs)
        if not normalized_hosts:
            raise PrivateNetworkContactError("private-network policy requires at least one exact host")
        if not normalized_cidrs:
            raise PrivateNetworkContactError("private-network policy requires at least one private CIDR")
        return cls(
            allow_private_network=True,
            allow_hosts=normalized_hosts,
            allow_cidrs=normalized_cidrs,
            allow_http=allow_http,
            follow_redirects=follow_redirects,
        )


@dataclass(frozen=True)
class PrivateContactReceipt:
    schema: str
    contacted_at_utc: str
    method: str
    requested_url: str
    final_url: str
    contacted_hosts: tuple[str, ...]
    resolved_ips: tuple[str, ...]
    status: int
    response_bytes: int
    response_sha256: str
    redirect_count: int

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _normalize_host(host: str) -> str:
    if not isinstance(host, str) or host != host.strip():
        raise PrivateNetworkContactError("allowlisted host must be a clean string")
    value = host.rstrip(".").lower()
    if not value or any(ch in value for ch in "/?#@"):
        raise PrivateNetworkContactError(f"invalid allowlisted host: {host!r}")
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PrivateNetworkContactError(f"invalid host: {host!r}") from exc


def _validate_private_cidr(raw: str) -> ipaddress._BaseNetwork:
    try:
        network = ipaddress.ip_network(raw, strict=False)
    except ValueError as exc:
        raise PrivateNetworkContactError(f"invalid private CIDR: {raw}") from exc

    if network.version == 4:
        permitted = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        if not any(network.subnet_of(parent) for parent in permitted):
            raise PrivateNetworkContactError(f"CIDR is not inside RFC1918 space: {raw}")
    else:
        ula = ipaddress.ip_network("fc00::/7")
        if not network.subnet_of(ula):
            raise PrivateNetworkContactError(f"CIDR is not inside IPv6 ULA space: {raw}")
    return network


def _parse_url(url: str, policy: PrivateNetworkPolicy) -> tuple[str, int]:
    if not policy.allow_private_network:
        raise PrivateNetworkContactError("allow_private_network is disabled")
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"https", "http"}:
        raise PrivateNetworkContactError("only http/https is supported")
    if scheme == "http" and not policy.allow_http:
        raise PrivateNetworkContactError("plain HTTP requires explicit allow_http")
    if parsed.username is not None or parsed.password is not None:
        raise PrivateNetworkContactError("credentials in URL authority are forbidden")
    if not parsed.hostname:
        raise PrivateNetworkContactError("URL has no hostname")
    host = _normalize_host(parsed.hostname)
    if host not in policy.allow_hosts:
        raise PrivateNetworkContactError(f"host is not explicitly allowlisted: {host}")
    default_port = 443 if scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise PrivateNetworkContactError("invalid URL port") from exc
    if port != default_port:
        raise PrivateNetworkContactError("non-default ports require a separate explicit connector")
    return host, port


def _resolve(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PrivateNetworkContactError(f"DNS resolution failed for {host}: {exc}") from exc
    return tuple(sorted({row[4][0] for row in rows}))


def _validate_resolved(policy: PrivateNetworkPolicy, host: str, resolved: Iterable[str]) -> tuple[str, ...]:
    networks = tuple(_validate_private_cidr(cidr) for cidr in policy.allow_cidrs)
    checked: set[str] = set()
    for raw in resolved:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise PrivateNetworkContactError(f"resolver returned invalid address: {raw}") from exc
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise PrivateNetworkContactError(f"special-use address blocked for {host}: {ip}")
        if not any(ip in network for network in networks):
            raise PrivateNetworkContactError(f"resolved address is outside approved private CIDRs: {ip}")
        checked.add(str(ip))
    if not checked:
        raise PrivateNetworkContactError(f"no approved private address resolved for {host}")
    return tuple(sorted(checked))


def _safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    out = {"User-Agent": "Senju-Private-Network/1.0"}
    forbidden = {
        "authorization", "cookie", "x-api-key", "proxy-authorization",
        "host", "content-length", "transfer-encoding", "connection",
    }
    for key, value in (headers or {}).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PrivateNetworkContactError("request headers must be strings")
        if key.lower() in forbidden:
            raise PrivateNetworkContactError(f"credential/control header is not allowed: {key}")
        if any(ch in key for ch in "\r\n:") or "\r" in value or "\n" in value:
            raise PrivateNetworkContactError("invalid request header")
        out[key] = value
    return out


class PrivateNetworkContactClient:
    """Read-only HTTP(S) client for explicitly authorized private ranges."""

    def __init__(
        self,
        policy: PrivateNetworkPolicy,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self.policy = policy
        self._resolver = resolver or _resolve
        if opener is None:
            self._open = urllib.request.build_opener(_NoRedirect()).open
        else:
            self._open = opener

    def contact(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
    ) -> PrivateContactReceipt:
        method = method.upper().strip()
        if method not in self.policy.allowed_methods:
            raise PrivateNetworkContactError(f"method is not allowed in private lane: {method}")

        requested_url = url
        current_url = url
        contacted_hosts: list[str] = []
        all_resolved: set[str] = set()
        redirects = 0
        safe_headers = _safe_headers(headers)

        while True:
            host, port = _parse_url(current_url, self.policy)
            resolved = _validate_resolved(self.policy, host, self._resolver(host, port))
            all_resolved.update(resolved)
            if not contacted_hosts or contacted_hosts[-1] != host:
                contacted_hosts.append(host)

            request = urllib.request.Request(current_url, headers=safe_headers, method=method)
            try:
                response = self._open(request, timeout=self.policy.timeout_seconds)
            except urllib.error.HTTPError as exc:
                response = exc

            status = int(getattr(response, "status", getattr(response, "code", 0)))
            response_headers = getattr(response, "headers", None)
            location = response_headers.get("Location") if response_headers is not None else None

            if status in {301, 302, 303, 307, 308} and location:
                if not self.policy.follow_redirects:
                    raise PrivateNetworkContactError("redirect blocked by policy")
                if redirects >= self.policy.max_redirects:
                    raise PrivateNetworkContactError("redirect limit exceeded")
                current_url = urllib.parse.urljoin(current_url, str(location))
                redirects += 1
                continue

            body = response.read(self.policy.max_response_bytes + 1)
            if len(body) > self.policy.max_response_bytes:
                raise PrivateNetworkContactError("response exceeds max_response_bytes")

            return PrivateContactReceipt(
                schema="senju-private-contact/v1",
                contacted_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                method=method,
                requested_url=requested_url,
                final_url=current_url,
                contacted_hosts=tuple(contacted_hosts),
                resolved_ips=tuple(sorted(all_resolved)),
                status=status,
                response_bytes=len(body),
                response_sha256=hashlib.sha256(body).hexdigest(),
                redirect_count=redirects,
            )
