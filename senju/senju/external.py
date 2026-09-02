"""Guarded outbound HTTP contact for Senju.

A bounded, auditable HTTP(S) transport for explicitly approved public hosts.
The transport is intentionally separate from the Arena target framework.

Capabilities:
- exact public-host allowlist and public-DNS validation;
- HTTPS by default;
- GET/HEAD/OPTIONS/POST/PUT/PATCH plus explicit opt-in DELETE;
- bounded request/response bodies and response-body capture;
- bounded retries;
- optional redirect following with every hop re-validated against the allowlist;
- cross-host redirects strip sensitive request headers;
- machine-readable receipts containing final URL, contacted hosts and redirect count.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class ExternalContactError(RuntimeError):
    """Fail-closed error raised before or during an external contact."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose provider redirect responses so Senju can validate every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class ExternalAuthorityScope:
    """Explicit, machine-readable authority contract for outbound connectors and API access.
    
    Adheres to the Senju autonomous expansion covenant: all external interaction lanes
    must declare explicit destination, action sets, rate limits, verification, and purpose.
    """

    scope_id: str
    target_service: str
    allow_hosts: frozenset[str]
    allowed_methods: frozenset[str] = field(
        default_factory=lambda: frozenset({"GET", "HEAD", "OPTIONS"})
    )
    allow_http: bool = False
    allow_delete: bool = False
    rate_limit_per_minute: int = 60
    timeout_seconds: float = 10.0
    max_request_bytes: int = 128 * 1024
    max_response_bytes: int = 1024 * 1024
    retries: int = 2
    follow_redirects: bool = True
    credential_scope: str = "none"  # "none" | "public_token" | "service_bearer"
    verification_strategy: str = "sha256_receipt"
    rollback_supported: bool = False
    description: str = ""

    def to_policy(self) -> ExternalContactPolicy:
        return ExternalContactPolicy(
            allow_hosts=self.allow_hosts,
            allow_http=self.allow_http,
            allowed_methods=self.allowed_methods,
            allow_delete=self.allow_delete,
            follow_redirects=self.follow_redirects,
            max_redirects=3,
            timeout_seconds=self.timeout_seconds,
            max_request_bytes=self.max_request_bytes,
            max_response_bytes=self.max_response_bytes,
            retries=self.retries,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "target_service": self.target_service,
            "allow_hosts": sorted(self.allow_hosts),
            "allowed_methods": sorted(self.allowed_methods),
            "allow_http": self.allow_http,
            "allow_delete": self.allow_delete,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "timeout_seconds": self.timeout_seconds,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "retries": self.retries,
            "follow_redirects": self.follow_redirects,
            "credential_scope": self.credential_scope,
            "verification_strategy": self.verification_strategy,
            "rollback_supported": self.rollback_supported,
            "description": self.description,
        }


BUILTIN_AUTHORITY_SCOPES: dict[str, ExternalAuthorityScope] = {
    "threat_intel_public": ExternalAuthorityScope(
        scope_id="threat_intel_public",
        target_service="Public Vulnerability & Threat Feeds",
        allow_hosts=frozenset({
            "services.nvd.nist.gov",
            "cve.circl.lu",
            "raw.githubusercontent.com",
            "api.github.com",
            "security.debian.org",
            "vuln.cisa.gov",
            "example.com",
        }),
        allowed_methods=frozenset({"GET", "HEAD"}),
        timeout_seconds=10.0,
        max_response_bytes=2 * 1024 * 1024,
        retries=2,
        follow_redirects=True,
        description="Public CVE and advisory telemetry feed ingestion for dynamic target generation",
    ),
    "github_metadata": ExternalAuthorityScope(
        scope_id="github_metadata",
        target_service="GitHub API and Releases",
        allow_hosts=frozenset({
            "api.github.com",
            "raw.githubusercontent.com",
            "github.com",
        }),
        allowed_methods=frozenset({"GET", "HEAD", "POST"}),
        timeout_seconds=15.0,
        max_response_bytes=4 * 1024 * 1024,
        retries=2,
        follow_redirects=True,
        credential_scope="public_token",
        description="GitHub repository status, release tracking, and commit verification",
    ),
    "canary_telemetry": ExternalAuthorityScope(
        scope_id="canary_telemetry",
        target_service="Observability & Canary Probes",
        allow_hosts=frozenset({
            "httpbin.org",
            "1.1.1.1",
            "dns.google",
            "example.com",
        }),
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS", "POST"}),
        timeout_seconds=5.0,
        max_response_bytes=512 * 1024,
        retries=1,
        follow_redirects=True,
        description="Live egress verification and transport resilience canary tests",
    ),
}


@dataclass(frozen=True)
class ExternalContactPolicy:
    """Policy for a Senju outbound-contact lane."""

    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_http: bool = False
    allowed_methods: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
        )
    )
    allow_delete: bool = False
    follow_redirects: bool = False
    max_redirects: int = 3
    timeout_seconds: float = 5.0
    max_request_bytes: int = 64 * 1024
    max_response_bytes: int = 512 * 1024
    retries: int = 1
    retry_backoff_seconds: float = 0.25

    @classmethod
    def from_authority_scope(cls, scope: ExternalAuthorityScope) -> "ExternalContactPolicy":
        return scope.to_policy()

    @classmethod
    def threat_intel(cls) -> "ExternalContactPolicy":
        return BUILTIN_AUTHORITY_SCOPES["threat_intel_public"].to_policy()

    @classmethod
    def from_hosts(
        cls,
        hosts: Iterable[str],
        *,
        allow_http: bool = False,
        allow_delete: bool = False,
        follow_redirects: bool = False,
        max_redirects: int = 3,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 512 * 1024,
        retries: int = 1,
    ) -> "ExternalContactPolicy":
        normalized = frozenset(_normalize_host(h) for h in hosts if h and h.strip())
        return cls(
            allow_hosts=normalized,
            allow_http=allow_http,
            allow_delete=allow_delete,
            follow_redirects=follow_redirects,
            max_redirects=max(0, min(int(max_redirects), 5)),
            timeout_seconds=max(0.5, min(float(timeout_seconds), 20.0)),
            max_response_bytes=max(1024, min(int(max_response_bytes), 10 * 1024 * 1024)),
            retries=max(0, min(int(retries), 5)),
        )


@dataclass(frozen=True)
class ContactReceipt:
    schema: str
    contacted_at_utc: str
    method: str
    requested_url: str
    final_url: str
    host: str
    final_host: str
    contacted_hosts: tuple[str, ...]
    resolved_ips: tuple[str, ...]
    status: int
    provider_acknowledged: bool
    response_bytes: int
    response_sha256: str
    content_type: str | None
    etag: str | None
    last_modified: str | None
    retry_after: str | None
    attempt_count: int
    redirect_count: int

    @property
    def url(self) -> str:
        return self.requested_url

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["url"] = self.requested_url
        return data

    def write(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ContactResult:
    receipt: ContactReceipt
    body: bytes

    def write_body(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.body)

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _normalize_host(host: str) -> str:
    if not isinstance(host, str):
        raise ExternalContactError("allowlisted host must be a string")
    if host != host.strip():
        raise ExternalContactError(f"allowlisted host has surrounding whitespace: {host!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in host):
        raise ExternalContactError(f"allowlisted host contains control characters: {host!r}")
    value = host.rstrip(".").lower()
    if not value or any(c in value for c in "/?#@"):
        raise ExternalContactError(f"invalid allowlisted host: {host!r}")
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ExternalContactError(f"invalid host: {host!r}") from exc


def _parse_url(url: str, policy: ExternalContactPolicy) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"https", "http"}:
        raise ExternalContactError("only http/https external contact is supported")
    if scheme == "http" and not policy.allow_http:
        raise ExternalContactError("plain HTTP is disabled; use HTTPS or explicitly allow HTTP")
    if parsed.username is not None or parsed.password is not None:
        raise ExternalContactError("credentials in URL authority are not allowed")
    if not parsed.hostname:
        raise ExternalContactError("URL has no hostname")
    host = _normalize_host(parsed.hostname)
    if host not in policy.allow_hosts:
        raise ExternalContactError(f"host is not explicitly allowlisted: {host}")
    default_port = 443 if scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise ExternalContactError("invalid URL port") from exc
    if port != default_port:
        raise ExternalContactError(
            f"non-default port is not covered by host-only authority: {host}:{port}"
        )
    return host, port


def _resolve_public(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ExternalContactError(f"DNS resolution failed for {host}: {exc}") from exc

    ips: set[str] = set()
    for row in rows:
        raw = row[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise ExternalContactError(f"resolver returned invalid address for {host}: {raw}") from exc
        if not ip.is_global:
            raise ExternalContactError(f"non-public address blocked for {host}: {ip}")
        ips.add(str(ip))
    if not ips:
        raise ExternalContactError(f"DNS resolution returned no usable address for {host}")
    return tuple(sorted(ips))


def _safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    out = {"User-Agent": "Senju-External-Contact/3.0"}
    forbidden = {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "proxy-authorization",
        "proxy-connection",
    }
    for key, value in (headers or {}).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ExternalContactError("request headers must be strings")
        if not key or any(c in key for c in "\r\n:"):
            raise ExternalContactError(f"invalid header name: {key!r}")
        if key.lower() in forbidden:
            raise ExternalContactError(f"caller-controlled header is not allowed: {key}")
        if "\r" in value or "\n" in value:
            raise ExternalContactError(f"invalid header value for {key}")
        out[key] = value
    return out


def _validate_resolved(host: str, resolved: Iterable[str]) -> tuple[str, ...]:
    checked: set[str] = set()
    for raw in resolved:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise ExternalContactError(f"resolver returned invalid address: {raw}") from exc
        if not ip.is_global:
            raise ExternalContactError(f"non-public address blocked for {host}: {ip}")
        checked.add(str(ip))
    if not checked:
        raise ExternalContactError(f"no public address resolved for {host}")
    return tuple(sorted(checked))


def _header(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return None if value is None else str(value)


def _strip_sensitive_cross_host(headers: Mapping[str, str]) -> dict[str, str]:
    sensitive = {"authorization", "cookie", "x-api-key", "proxy-authorization"}
    return {k: v for k, v in headers.items() if k.lower() not in sensitive}


class ExternalContactClient:
    """Perform bounded, allowlisted outbound HTTP contact and emit evidence."""

    def __init__(
        self,
        policy: ExternalContactPolicy,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        opener: Callable[..., object] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.policy = policy
        self._resolver = resolver or _resolve_public
        if opener is None:
            built = urllib.request.build_opener(_NoRedirect())
            self._open = built.open
        else:
            self._open = opener
        self._sleep = sleeper or time.sleep

    def contact(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ContactReceipt:
        return self.contact_with_body(url, method=method, body=body, headers=headers).receipt

    def contact_with_body(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ContactResult:
        requested_url = url
        method = method.upper().strip()
        if method not in self.policy.allowed_methods:
            raise ExternalContactError(f"method is not allowed: {method}")
        if method == "DELETE" and not self.policy.allow_delete:
            raise ExternalContactError("DELETE requires explicit allow_delete opt-in")
        body_methods = {"POST", "PUT", "PATCH", "DELETE"}
        if body is not None and method not in body_methods:
            raise ExternalContactError("request body is supported only for POST/PUT/PATCH/DELETE")
        payload = body or b""
        if len(payload) > self.policy.max_request_bytes:
            raise ExternalContactError(
                f"request body exceeds {self.policy.max_request_bytes} bytes"
            )

        current_url = url
        current_method = method
        current_payload = payload
        current_headers = _safe_headers(headers)
        contacted_hosts: list[str] = []
        all_resolved: set[str] = set()
        redirects = 0
        total_attempts = 0

        while True:
            host, port = _parse_url(current_url, self.policy)
            resolved = _validate_resolved(host, self._resolver(host, port))
            all_resolved.update(resolved)
            if not contacted_hosts or contacted_hosts[-1] != host:
                contacted_hosts.append(host)

            req = urllib.request.Request(
                current_url,
                data=(current_payload if current_method in body_methods and current_payload else None),
                headers=current_headers,
                method=current_method,
            )

            attempts = self.policy.retries + 1
            last_error: Exception | None = None
            redirect_location: str | None = None
            response_headers: object = None

            for attempt in range(1, attempts + 1):
                total_attempts += 1
                try:
                    response = self._open(req, timeout=self.policy.timeout_seconds)
                    status = int(response.status)
                    response_headers = response.headers
                    data = b"" if current_method == "HEAD" else response.read(self.policy.max_response_bytes + 1)
                    try:
                        response.close()
                    except Exception:
                        pass
                    break
                except urllib.error.HTTPError as exc:
                    status = int(exc.code)
                    response_headers = exc.headers
                    if status in {301, 302, 303, 307, 308}:
                        redirect_location = _header(exc.headers, "Location")
                    data = b"" if current_method == "HEAD" else exc.read(self.policy.max_response_bytes + 1)
                    break
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    last_error = exc
                    if attempt >= attempts:
                        raise ExternalContactError(
                            f"external contact failed after {attempt} attempt(s): {exc}"
                        ) from exc
                    self._sleep(self.policy.retry_backoff_seconds * attempt)
            else:  # pragma: no cover
                raise ExternalContactError(f"external contact failed: {last_error}")

            if len(data) > self.policy.max_response_bytes:
                raise ExternalContactError(
                    f"response exceeds {self.policy.max_response_bytes} byte safety limit"
                )

            if (
                self.policy.follow_redirects
                and status in {301, 302, 303, 307, 308}
                and redirect_location
            ):
                if redirects >= self.policy.max_redirects:
                    raise ExternalContactError(
                        f"redirect limit exceeded ({self.policy.max_redirects})"
                    )
                next_url = urllib.parse.urljoin(current_url, redirect_location)
                next_host, _ = _parse_url(next_url, self.policy)
                if next_host != host:
                    current_headers = _strip_sensitive_cross_host(current_headers)
                if status == 303 or (status in {301, 302} and current_method == "POST"):
                    current_method = "GET"
                    current_payload = b""
                    current_headers = {
                        k: v
                        for k, v in current_headers.items()
                        if k.lower() not in {"content-type", "content-encoding"}
                    }
                current_url = next_url
                redirects += 1
                continue

            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            final_host, _ = _parse_url(current_url, self.policy)
            receipt = ContactReceipt(
                schema="senju-external-contact/v3",
                contacted_at_utc=now,
                method=method,
                requested_url=requested_url,
                final_url=current_url,
                host=_parse_url(requested_url, self.policy)[0],
                final_host=final_host,
                contacted_hosts=tuple(contacted_hosts),
                resolved_ips=tuple(sorted(all_resolved)),
                status=status,
                provider_acknowledged=200 <= status < 400,
                response_bytes=len(data),
                response_sha256=hashlib.sha256(data).hexdigest(),
                content_type=_header(response_headers, "Content-Type"),
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
                retry_after=_header(response_headers, "Retry-After"),
                attempt_count=total_attempts,
                redirect_count=redirects,
            )
            return ContactResult(receipt=receipt, body=data)