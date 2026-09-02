"""SPEAR phase 5A: authorized TLS/certificate observation.

Only exact HTTPS hosts already present in a valid EngagementManifest are
contacted. This module performs a TLS handshake and records sanitized metadata;
it does not send HTTP requests, credentials, or exploit payloads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import ssl
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .authorized_assessment import EngagementError, EngagementManifest, EngagementTarget


@dataclass(frozen=True)
class TLSFinding:
    severity: str
    key: str
    title: str
    evidence: str
    remediation: str


@dataclass
class TLSReport:
    schema: str
    engagement_id: str
    authorization_reference: str
    manifest_sha256: str
    target_host: str
    observed_at_utc: str
    tls_version: str
    cipher: str
    certificate_subject_cn: str | None
    certificate_issuer_cn: str | None
    certificate_not_after_utc: str | None
    san_dns_count: int
    findings: list[TLSFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "findings": [asdict(item) for item in self.findings],
            "boundaries": {
                "exact_host_only": True,
                "http_requests": 0,
                "credential_guessing": False,
                "exploit_delivery": False,
                "raw_certificate_persisted": False,
            },
        }


def _target(manifest: EngagementManifest, host: str) -> EngagementTarget:
    normalized = host.strip().rstrip(".").lower()
    for item in manifest.targets:
        if item.host == normalized:
            return item
    raise EngagementError(f"host is not part of engagement: {normalized}")


def _cn(rows: Any) -> str | None:
    for row in rows or ():
        for key, value in row:
            if str(key).lower() == "commonname":
                return str(value)
    return None


def _parse_cert_time(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        stamp = ssl.cert_time_to_seconds(raw)
    except Exception:
        return None
    return dt.datetime.fromtimestamp(stamp, tz=dt.timezone.utc)


def _collect_tls(host: str, port: int, timeout: float) -> dict[str, Any]:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as conn:
            cert = conn.getpeercert() or {}
            cipher = conn.cipher() or ("", "", 0)
            sans = [value for kind, value in cert.get("subjectAltName", ()) if kind == "DNS"]
            return {
                "tls_version": conn.version() or "unknown",
                "cipher": str(cipher[0] or "unknown"),
                "subject_cn": _cn(cert.get("subject")),
                "issuer_cn": _cn(cert.get("issuer")),
                "not_after": cert.get("notAfter"),
                "san_dns_count": len(sans),
            }


class AuthorizedTLSInspector:
    def __init__(
        self,
        manifest: EngagementManifest,
        target_host: str,
        *,
        collector: Callable[[str, int, float], dict[str, Any]] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.manifest = manifest
        self.target = _target(manifest, target_host)
        self.collector = collector or _collect_tls
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 10.0))

    def run(self, *, now: dt.datetime | None = None) -> TLSReport:
        current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        self.manifest.validate(now=current, enforce_window=True)
        self.target.validate(allow_http=self.manifest.allow_http)
        if self.target.scheme != "https":
            raise EngagementError("TLS observation requires an HTTPS engagement target")

        data = self.collector(self.target.host, 443, self.timeout_seconds)
        not_after = _parse_cert_time(data.get("not_after"))
        findings: list[TLSFinding] = []
        if not_after is not None:
            days = (not_after - current).total_seconds() / 86400.0
            if days < 0:
                findings.append(TLSFinding(
                    "critical", "certificate-expired", "TLS certificate is expired",
                    f"certificate expired {abs(days):.1f} days ago",
                    "Renew and deploy a valid certificate immediately.",
                ))
            elif days < 14:
                findings.append(TLSFinding(
                    "high", "certificate-expiry-imminent", "TLS certificate expires soon",
                    f"certificate expires in {days:.1f} days",
                    "Renew the certificate and verify automated renewal before expiry.",
                ))
            elif days < 30:
                findings.append(TLSFinding(
                    "medium", "certificate-expiry-near", "TLS certificate renewal window is near",
                    f"certificate expires in {days:.1f} days",
                    "Confirm automated renewal and deployment are functioning.",
                ))

        version = str(data.get("tls_version") or "unknown")
        if version in {"TLSv1", "TLSv1.1", "SSLv3", "SSLv2"}:
            findings.append(TLSFinding(
                "high", "legacy-tls", "Legacy TLS protocol negotiated", version,
                "Disable legacy protocol versions and require TLS 1.2 or newer.",
            ))

        return TLSReport(
            schema="senju-spear-tls/v1",
            engagement_id=self.manifest.engagement_id,
            authorization_reference=self.manifest.authorization_reference,
            manifest_sha256=self.manifest.sha256(),
            target_host=self.target.host,
            observed_at_utc=current.isoformat(timespec="seconds"),
            tls_version=version,
            cipher=str(data.get("cipher") or "unknown"),
            certificate_subject_cn=data.get("subject_cn"),
            certificate_issuer_cn=data.get("issuer_cn"),
            certificate_not_after_utc=(not_after.isoformat(timespec="seconds") if not_after else None),
            san_dns_count=max(0, int(data.get("san_dns_count") or 0)),
            findings=findings,
        )


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run authorized SPEAR TLS observation")
    p.add_argument("manifest")
    p.add_argument("--target-host", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args(list(argv) if argv is not None else None)
    manifest = EngagementManifest.load(args.manifest)
    report = AuthorizedTLSInspector(manifest, args.target_host, timeout_seconds=args.timeout).run()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
