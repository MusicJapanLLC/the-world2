"""SPEAR phase 2: authorized, non-destructive web posture assessment.

This pack is intentionally limited to low-impact HTTP observations on exact
hosts already authorized by an EngagementManifest. It does not implement
credential guessing, auth bypass, exploit payload delivery, persistence,
destructive requests, or lateral movement.
"""
from __future__ import annotations

import argparse
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
from typing import Any, Callable, Mapping

from .authorized_assessment import EngagementError, EngagementManifest, EngagementTarget


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DANGEROUS_ADVERTISED_METHODS = frozenset({"TRACE", "PUT", "DELETE", "PATCH", "CONNECT"})
MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class WebProbeReceipt:
    check: str
    method: str
    url: str
    status: int
    elapsed_ms: float
    response_bytes: int
    response_sha256: str
    headers: dict[str, str]


@dataclass(frozen=True)
class WebFinding:
    severity: str
    key: str
    title: str
    evidence: str
    remediation: str


@dataclass
class WebPostureReport:
    schema: str
    engagement_id: str
    authorization_reference: str
    manifest_sha256: str
    target_host: str
    target_url: str
    started_at_utc: str
    completed_at_utc: str
    requests_used: int
    findings: list[WebFinding] = field(default_factory=list)
    receipts: list[WebProbeReceipt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "engagement_id": self.engagement_id,
            "authorization_reference": self.authorization_reference,
            "manifest_sha256": self.manifest_sha256,
            "target_host": self.target_host,
            "target_url": self.target_url,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "requests_used": self.requests_used,
            "findings": [asdict(item) for item in self.findings],
            "receipts": [asdict(item) for item in self.receipts],
            "severity_counts": {
                severity: sum(1 for item in self.findings if item.severity == severity)
                for severity in ("critical", "high", "medium", "low", "info")
            },
            "boundaries": {
                "credential_guessing": False,
                "auth_bypass": False,
                "exploit_delivery": False,
                "persistence": False,
                "destructive_requests": False,
                "lateral_movement": False,
                "methods": sorted(SAFE_METHODS),
                "exact_host_only": True,
            },
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _resolve_public(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EngagementError(f"DNS resolution failed for {host}: {exc}") from exc
    ips: set[str] = set()
    for row in rows:
        raw = row[4][0]
        ip = ipaddress.ip_address(raw)
        if not ip.is_global:
            raise EngagementError(f"non-public address blocked for external SPEAR target {host}: {ip}")
        ips.add(str(ip))
    if not ips:
        raise EngagementError(f"DNS returned no public addresses for {host}")
    return tuple(sorted(ips))


def _target_for_host(manifest: EngagementManifest, host: str) -> EngagementTarget:
    normalized = host.strip().rstrip(".").lower()
    for target in manifest.targets:
        if target.host == normalized:
            return target
    raise EngagementError(f"host is not part of engagement: {normalized}")


def _header_map(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    items = getattr(headers, "items", None)
    if items is None:
        return {}
    return {str(k).lower(): str(v) for k, v in items()}


def _url_for(target: EngagementTarget, path: str | None = None) -> str:
    return target.url(path)


class AuthorizedWebPostureEngine:
    """Run a bounded web posture pack under a currently-valid engagement."""

    def __init__(
        self,
        manifest: EngagementManifest,
        target_host: str,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.manifest = manifest
        self.target = _target_for_host(manifest, target_host)
        self._resolver = resolver or _resolve_public
        self._sleep = sleeper or time.sleep
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 10.0))
        if opener is None:
            built = urllib.request.build_opener(_NoRedirect())
            self._open = built.open
        else:
            self._open = opener
        self._receipts: list[WebProbeReceipt] = []
        self._last_request_at = 0.0

    def _authorize_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != self.target.scheme:
            raise EngagementError("probe scheme drifted outside engagement target")
        host = (parsed.hostname or "").strip().rstrip(".").lower()
        if host != self.target.host:
            raise EngagementError(f"probe host drifted outside exact target: {host}")
        target_path = parsed.path or "/"
        base = self.target.base_path
        if base != "/" and not (target_path == base or target_path.startswith(base.rstrip("/") + "/")):
            raise EngagementError(f"probe path is outside target base_path: {target_path}")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._resolver(host, port)

    def _throttle(self) -> None:
        gap = 1.0 / self.manifest.max_rps
        remaining = gap - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)

    def _request(
        self,
        check: str,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
    ) -> WebProbeReceipt:
        method = method.upper()
        if method not in SAFE_METHODS:
            raise EngagementError(f"method is outside SPEAR web posture pack: {method}")
        if len(self._receipts) >= self.manifest.max_requests_per_target:
            raise EngagementError("engagement request budget exhausted")
        self._authorize_url(url)
        self._throttle()
        request_headers = {
            "User-Agent": "Senju-SPEAR-Web/1.0",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        }
        for key, value in (headers or {}).items():
            if any(ch in key for ch in "\r\n:") or "\r" in value or "\n" in value:
                raise EngagementError("invalid probe header")
            request_headers[key] = value
        req = urllib.request.Request(url, method=method, headers=request_headers)
        started = time.monotonic()
        body = b""
        status = 0
        response_headers: dict[str, str] = {}
        try:
            response = self._open(req, timeout=self.timeout_seconds)
            status = int(response.status)
            if method != "HEAD":
                body = response.read(MAX_BODY_BYTES + 1)
            response_headers = _header_map(response.headers)
            try:
                response.close()
            except Exception:
                pass
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            if method != "HEAD":
                body = exc.read(MAX_BODY_BYTES + 1)
            response_headers = _header_map(exc.headers)

        if len(body) > MAX_BODY_BYTES:
            raise EngagementError(f"response exceeds {MAX_BODY_BYTES} byte SPEAR limit")
        self._last_request_at = time.monotonic()
        receipt = WebProbeReceipt(
            check=check,
            method=method,
            url=url,
            status=status,
            elapsed_ms=round((time.monotonic() - started) * 1000.0, 2),
            response_bytes=len(body),
            response_sha256=hashlib.sha256(body).hexdigest(),
            headers=response_headers,
        )
        self._receipts.append(receipt)
        return receipt

    def run(self, *, now: dt.datetime | None = None) -> WebPostureReport:
        current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        self.manifest.validate(now=current, enforce_window=True)
        self.target.validate(allow_http=self.manifest.allow_http)
        started = current.isoformat(timespec="seconds")
        findings: list[WebFinding] = []

        root_url = _url_for(self.target)
        root = self._request("root", "GET", root_url)
        self._check_security_headers(root, self.target.scheme, findings)
        self._check_cookie_flags(root, findings)
        self._check_banner(root, findings)
        self._check_redirect_boundary(root, findings)

        if len(self._receipts) < self.manifest.max_requests_per_target:
            head = self._request("head", "HEAD", root_url)
            if head.status >= 500:
                findings.append(WebFinding(
                    "medium",
                    "head-5xx",
                    "HEAD request causes a server error",
                    f"HEAD returned HTTP {head.status}",
                    "Handle HEAD consistently or explicitly reject it without a 5xx response.",
                ))

        if len(self._receipts) < self.manifest.max_requests_per_target:
            options = self._request(
                "options",
                "OPTIONS",
                root_url,
                {
                    "Origin": "https://senju.invalid",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            self._check_cors(options, findings)
            self._check_advertised_methods(options, findings)

        if len(self._receipts) < self.manifest.max_requests_per_target:
            security = self._request(
                "security_txt", "GET", _url_for(self.target, "/.well-known/security.txt")
            )
            if not 200 <= security.status < 300 or security.response_bytes == 0:
                findings.append(WebFinding(
                    "info",
                    "security-txt-missing",
                    "security.txt was not observed",
                    f"/.well-known/security.txt returned HTTP {security.status} with {security.response_bytes} bytes",
                    "Publish RFC 9116 security.txt if an external vulnerability-reporting contact is desired.",
                ))

        if len(self._receipts) < self.manifest.max_requests_per_target:
            self._request("robots_txt", "GET", _url_for(self.target, "/robots.txt"))

        completed = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        return WebPostureReport(
            schema="senju-spear-web-posture/v1",
            engagement_id=self.manifest.engagement_id,
            authorization_reference=self.manifest.authorization_reference,
            manifest_sha256=self.manifest.sha256(),
            target_host=self.target.host,
            target_url=root_url,
            started_at_utc=started,
            completed_at_utc=completed.isoformat(timespec="seconds"),
            requests_used=len(self._receipts),
            findings=findings,
            receipts=list(self._receipts),
        )

    @staticmethod
    def _check_security_headers(
        receipt: WebProbeReceipt,
        scheme: str,
        findings: list[WebFinding],
    ) -> None:
        headers = receipt.headers
        if scheme == "https" and "strict-transport-security" not in headers:
            findings.append(WebFinding(
                "medium", "hsts-missing", "HSTS is missing",
                "HTTPS root response omitted Strict-Transport-Security",
                "Enable HSTS after confirming required subdomains support HTTPS.",
            ))
        expected = {
            "content-security-policy": (
                "medium", "csp-missing", "Content-Security-Policy is missing",
                "Deploy a restrictive CSP appropriate to the application.",
            ),
            "x-content-type-options": (
                "low", "xcto-missing", "X-Content-Type-Options is missing",
                "Set X-Content-Type-Options: nosniff.",
            ),
            "referrer-policy": (
                "low", "referrer-policy-missing", "Referrer-Policy is missing",
                "Set an explicit Referrer-Policy such as strict-origin-when-cross-origin.",
            ),
        }
        for header, (severity, key, title, remediation) in expected.items():
            if header not in headers:
                findings.append(WebFinding(
                    severity, key, title, f"Root response omitted {header}", remediation
                ))

    @staticmethod
    def _check_cookie_flags(receipt: WebProbeReceipt, findings: list[WebFinding]) -> None:
        raw = receipt.headers.get("set-cookie", "")
        if not raw:
            return
        lower = raw.lower()
        if "secure" not in lower:
            findings.append(WebFinding(
                "medium", "cookie-secure-missing", "Cookie may lack Secure",
                raw[:240], "Mark authentication/session cookies Secure.",
            ))
        if "httponly" not in lower:
            findings.append(WebFinding(
                "medium", "cookie-httponly-missing", "Cookie may lack HttpOnly",
                raw[:240], "Mark authentication/session cookies HttpOnly when script access is unnecessary.",
            ))
        if "samesite" not in lower:
            findings.append(WebFinding(
                "low", "cookie-samesite-missing", "Cookie may lack SameSite",
                raw[:240], "Set an explicit SameSite policy appropriate to the application flow.",
            ))

    @staticmethod
    def _check_banner(receipt: WebProbeReceipt, findings: list[WebFinding]) -> None:
        for header in ("server", "x-powered-by"):
            if header in receipt.headers:
                findings.append(WebFinding(
                    "low",
                    f"banner-{header}",
                    f"Technology banner exposed: {header}",
                    receipt.headers[header][:200],
                    "Reduce unnecessary version/technology disclosure where practical.",
                ))

    @staticmethod
    def _check_cors(receipt: WebProbeReceipt, findings: list[WebFinding]) -> None:
        origin = receipt.headers.get("access-control-allow-origin", "")
        credentials = receipt.headers.get("access-control-allow-credentials", "").lower() == "true"
        if origin == "*" and credentials:
            findings.append(WebFinding(
                "high", "cors-wildcard-credentials",
                "CORS advertises wildcard origin with credentials",
                "Access-Control-Allow-Origin: * with Access-Control-Allow-Credentials: true",
                "Use an explicit trusted origin allowlist for credentialed CORS.",
            ))
        elif origin == "https://senju.invalid":
            findings.append(WebFinding(
                "high", "cors-origin-reflection", "CORS appears to reflect an arbitrary Origin",
                "Probe Origin https://senju.invalid was reflected",
                "Validate Origin against an explicit trusted allowlist before echoing it.",
            ))

    @staticmethod
    def _check_advertised_methods(receipt: WebProbeReceipt, findings: list[WebFinding]) -> None:
        allow = receipt.headers.get("allow", "")
        advertised = {item.strip().upper() for item in allow.split(",") if item.strip()}
        risky = sorted(advertised & DANGEROUS_ADVERTISED_METHODS)
        if risky:
            findings.append(WebFinding(
                "medium", "dangerous-methods-advertised",
                "Potentially dangerous HTTP methods are advertised",
                f"Allow: {', '.join(sorted(advertised))}",
                "Expose only methods required by the application and enforce authorization server-side.",
            ))

    def _check_redirect_boundary(
        self,
        receipt: WebProbeReceipt,
        findings: list[WebFinding],
    ) -> None:
        if receipt.status not in {301, 302, 303, 307, 308}:
            return
        location = receipt.headers.get("location")
        if not location:
            return
        destination = urllib.parse.urljoin(receipt.url, location)
        host = (urllib.parse.urlsplit(destination).hostname or "").strip().rstrip(".").lower()
        if host and host != self.target.host:
            findings.append(WebFinding(
                "info", "cross-host-redirect",
                "Root redirects to a different host",
                f"Location points to {destination}",
                "Confirm the destination is intended and separately authorized before deeper assessment.",
            ))


def _write_json(data: Mapping[str, Any], path: str | Path | None) -> None:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(rendered, end="")
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the authorized Senju SPEAR web posture pack")
    parser.add_argument("manifest", help="engagement manifest JSON")
    parser.add_argument("--target-host", required=True, help="exact host from the engagement")
    parser.add_argument("--out", help="write report JSON to this path")
    args = parser.parse_args(argv)

    manifest = EngagementManifest.load(args.manifest)
    report = AuthorizedWebPostureEngine(manifest, args.target_host).run()
    _write_json(report.to_dict(), args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
