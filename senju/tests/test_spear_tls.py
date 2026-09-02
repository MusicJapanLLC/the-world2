from __future__ import annotations

import datetime as dt

import pytest

from senju.authorized_assessment import EngagementError, EngagementManifest
from senju.spear_tls import AuthorizedTLSInspector


def manifest(scheme: str = "https") -> EngagementManifest:
    now = dt.datetime.now(dt.timezone.utc)
    return EngagementManifest.from_dict({
        "engagement_id": "test-engagement",
        "owner": "owner",
        "authorization_reference": "ticket-1",
        "valid_from_utc": (now - dt.timedelta(minutes=1)).isoformat(),
        "valid_until_utc": (now + dt.timedelta(hours=1)).isoformat(),
        "targets": [{"host": "owned.example", "scheme": scheme, "base_path": "/"}],
        "max_requests_per_target": 5,
        "max_rps": 1.0,
        "allow_http": scheme == "http",
        "destructive": False,
    })


def collector(host: str, port: int, timeout: float):
    assert host == "owned.example"
    assert port == 443
    assert timeout <= 10
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=90)
    return {
        "tls_version": "TLSv1.3",
        "cipher": "TLS_AES_256_GCM_SHA384",
        "subject_cn": "owned.example",
        "issuer_cn": "Example CA",
        "not_after": future.strftime("%b %d %H:%M:%S %Y GMT"),
        "san_dns_count": 2,
    }


def test_tls_observation_is_sanitized_and_exact_host_only() -> None:
    report = AuthorizedTLSInspector(manifest(), "owned.example", collector=collector).run()
    data = report.to_dict()
    assert data["schema"] == "senju-spear-tls/v1"
    assert data["target_host"] == "owned.example"
    assert data["tls_version"] == "TLSv1.3"
    assert data["boundaries"]["http_requests"] == 0
    assert data["boundaries"]["raw_certificate_persisted"] is False
    assert data["findings"] == []


def test_tls_rejects_host_outside_engagement() -> None:
    with pytest.raises(EngagementError, match="not part of engagement"):
        AuthorizedTLSInspector(manifest(), "other.example", collector=collector)


def test_tls_rejects_plain_http_target() -> None:
    with pytest.raises(EngagementError, match="requires an HTTPS"):
        AuthorizedTLSInspector(manifest("http"), "owned.example", collector=collector).run()


def test_tls_flags_near_expiry() -> None:
    def near(host: str, port: int, timeout: float):
        result = collector(host, port, timeout)
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
        result["not_after"] = future.strftime("%b %d %H:%M:%S %Y GMT")
        return result

    report = AuthorizedTLSInspector(manifest(), "owned.example", collector=near).run()
    assert any(item.key == "certificate-expiry-imminent" for item in report.findings)
