"""Trusted-owner execution path for Senju.

This module removes per-run engagement ceremony for assets already covered by an
Owner/BOSS trusted scope. A trusted scope is configured once with one or more
owned/explicitly-authorized domain roots. Red may then choose concrete hosts,
methods, order, retries and request plans inside those roots without a new
engagement_id, validity window, or exact-host manifest for every run.

This module intentionally does not create an unrestricted Internet-wide target
selector. The persistent trusted scope is the authorization boundary.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .external import ExternalContactClient, ExternalContactError, ExternalContactPolicy


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})


class TrustedScopeError(RuntimeError):
    """Raised when a request is outside the persistent Owner/BOSS trusted scope."""


def _host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    if not host or any(ch in host for ch in "/?#@*"):
        raise TrustedScopeError(f"invalid trusted domain root: {value!r}")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise TrustedScopeError(f"invalid trusted domain root: {value!r}") from exc


def _url_host(url: str, *, allow_http: bool) -> str:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"https", "http"}:
        raise TrustedScopeError("only http/https targets are supported")
    if scheme == "http" and not allow_http:
        raise TrustedScopeError("plain HTTP is disabled for this trusted scope")
    if parsed.username is not None or parsed.password is not None:
        raise TrustedScopeError("credentials in URL authority are not allowed")
    if not parsed.hostname:
        raise TrustedScopeError("target URL has no hostname")
    return _host(parsed.hostname)


@dataclass(frozen=True)
class TrustedOwnerScope:
    """Persistent Owner/BOSS scope; no per-run engagement id or expiry required."""

    domain_roots: frozenset[str]
    scope_id: str = "owner-default"
    owner: str = "Owner/BOSS"
    effect_level: str = "observe"  # observe | state_change
    allowed_methods: frozenset[str] = field(default_factory=lambda: DEFAULT_METHODS)
    allow_http: bool = False
    follow_redirects: bool = True
    max_redirects: int = 8
    max_rps: float = 10.0
    timeout_seconds: float = 15.0
    max_request_bytes: int = 1024 * 1024
    max_response_bytes: int = 8 * 1024 * 1024
    retries: int = 3

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TrustedOwnerScope":
        roots_raw = raw.get("domain_roots", raw.get("domain_suffixes", []))
        if not isinstance(roots_raw, list) or not roots_raw:
            raise TrustedScopeError("trusted scope requires at least one domain_root")
        roots = frozenset(_host(str(item)) for item in roots_raw if str(item).strip())
        if not roots:
            raise TrustedScopeError("trusted scope requires at least one domain_root")

        methods_raw = raw.get("allowed_methods", sorted(DEFAULT_METHODS))
        if not isinstance(methods_raw, list):
            raise TrustedScopeError("allowed_methods must be a list")
        methods = frozenset(str(item).upper().strip() for item in methods_raw if str(item).strip())
        unknown = methods - DEFAULT_METHODS
        if unknown:
            raise TrustedScopeError(f"unsupported methods: {sorted(unknown)}")
        if not methods:
            raise TrustedScopeError("allowed_methods cannot be empty")

        effect = str(raw.get("effect_level", "observe")).strip().lower()
        if effect not in {"observe", "state_change"}:
            raise TrustedScopeError("effect_level must be observe or state_change")

        return cls(
            domain_roots=roots,
            scope_id=str(raw.get("scope_id", "owner-default")).strip() or "owner-default",
            owner=str(raw.get("owner", "Owner/BOSS")).strip() or "Owner/BOSS",
            effect_level=effect,
            allowed_methods=methods,
            allow_http=bool(raw.get("allow_http", False)),
            follow_redirects=bool(raw.get("follow_redirects", True)),
            max_redirects=max(0, min(int(raw.get("max_redirects", 8)), 12)),
            max_rps=max(0.1, min(float(raw.get("max_rps", 10.0)), 20.0)),
            timeout_seconds=max(0.5, min(float(raw.get("timeout_seconds", 15.0)), 30.0)),
            max_request_bytes=max(1024, min(int(raw.get("max_request_bytes", 1024 * 1024)), 4 * 1024 * 1024)),
            max_response_bytes=max(1024, min(int(raw.get("max_response_bytes", 8 * 1024 * 1024)), 16 * 1024 * 1024)),
            retries=max(0, min(int(raw.get("retries", 3)), 5)),
        )

    @classmethod
    def load(cls, path: str | Path) -> "TrustedOwnerScope":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TrustedScopeError("trusted scope must be a JSON object")
        return cls.from_dict(raw)

    def allows_host(self, host: str) -> bool:
        normalized = _host(host)
        return any(normalized == root or normalized.endswith("." + root) for root in self.domain_roots)

    def allows_url(self, url: str) -> bool:
        return self.allows_host(_url_host(url, allow_http=self.allow_http))

    def policy_for_url(self, url: str, *, method: str) -> ExternalContactPolicy:
        host = _url_host(url, allow_http=self.allow_http)
        if not self.allows_host(host):
            raise TrustedScopeError(f"target is outside trusted owner scope: {host}")

        normalized_method = method.upper().strip()
        if normalized_method not in self.allowed_methods:
            raise TrustedScopeError(f"method is outside trusted owner scope: {normalized_method}")
        if normalized_method in WRITE_METHODS and self.effect_level != "state_change":
            raise TrustedScopeError(
                f"{normalized_method} requires effect_level=state_change in the persistent trusted scope"
            )

        # Exact-host allowlisting is derived automatically from the trusted domain root.
        # Red does not need to pre-enumerate each concrete subdomain in a per-run manifest.
        redirect_roots = {root for root in self.domain_roots if host == root}
        return ExternalContactPolicy(
            allow_hosts=frozenset({host, *redirect_roots}),
            allow_http=self.allow_http,
            allowed_methods=self.allowed_methods,
            allow_delete=self.effect_level == "state_change" and "DELETE" in self.allowed_methods,
            follow_redirects=self.follow_redirects,
            max_redirects=self.max_redirects,
            timeout_seconds=self.timeout_seconds,
            max_request_bytes=self.max_request_bytes,
            max_response_bytes=self.max_response_bytes,
            retries=self.retries,
            retry_backoff_seconds=0.15,
        )


@dataclass(frozen=True)
class TrustedRequest:
    url: str
    method: str = "GET"
    body: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TrustedRequest":
        headers = raw.get("headers", {})
        if not isinstance(headers, dict):
            raise TrustedScopeError("request headers must be an object")
        return cls(
            url=str(raw.get("url", "")).strip(),
            method=str(raw.get("method", "GET")).upper().strip(),
            body=None if raw.get("body") is None else str(raw.get("body")),
            headers={str(k): str(v) for k, v in headers.items()},
        )


class TrustedScopeRunner:
    """Execute Red-selected requests inside a persistent trusted domain scope."""

    def __init__(
        self,
        scope: TrustedOwnerScope,
        *,
        client_factory: Callable[[ExternalContactPolicy], ExternalContactClient] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.scope = scope
        self._client_factory = client_factory or (lambda policy: ExternalContactClient(policy))
        self._sleep = sleeper or time.sleep

    def run(self, requests: Iterable[TrustedRequest]) -> dict[str, Any]:
        items = list(requests)
        if not items:
            raise TrustedScopeError("at least one trusted request is required")

        interval = 1.0 / self.scope.max_rps
        observations: list[dict[str, Any]] = []

        for index, request in enumerate(items):
            if not request.url:
                raise TrustedScopeError("request URL is required")
            policy = self.scope.policy_for_url(request.url, method=request.method)
            client = self._client_factory(policy)
            body = None if request.body is None else request.body.encode("utf-8")
            try:
                result = client.contact_with_body(
                    request.url,
                    method=request.method,
                    body=body,
                    headers=request.headers,
                )
            except ExternalContactError as exc:
                raise TrustedScopeError(str(exc)) from exc

            receipt = result.receipt
            observations.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "status": receipt.status,
                    "final_url": receipt.final_url,
                    "contacted_hosts": list(receipt.contacted_hosts),
                    "redirect_count": receipt.redirect_count,
                    "attempt_count": receipt.attempt_count,
                    "response_bytes": receipt.response_bytes,
                    "response_sha256": receipt.response_sha256,
                    "provider_acknowledged": receipt.provider_acknowledged,
                }
            )
            if index < len(items) - 1:
                self._sleep(interval)

        return {
            "schema": "senju-trusted-owner-scope/v1",
            "scope_id": self.scope.scope_id,
            "owner": self.scope.owner,
            "effect_level": self.scope.effect_level,
            "domain_roots": sorted(self.scope.domain_roots),
            "engagement_id_required": False,
            "validity_window_required": False,
            "exact_host_manifest_required": False,
            "request_count": len(observations),
            "observations": observations,
        }


def _load_requests(path: str | Path) -> tuple[TrustedRequest, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("requests", [raw])
    if not isinstance(raw, list):
        raise TrustedScopeError("request plan must be a list or an object with requests")
    return tuple(TrustedRequest.from_dict(item) for item in raw)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju inside a persistent trusted Owner/BOSS scope")
    parser.add_argument("scope", help="trusted owner scope JSON")
    parser.add_argument("requests", help="Red-selected request plan JSON")
    parser.add_argument("--out", help="write sanitized execution report JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    scope = TrustedOwnerScope.load(args.scope)
    report = TrustedScopeRunner(scope).run(_load_requests(args.requests))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
