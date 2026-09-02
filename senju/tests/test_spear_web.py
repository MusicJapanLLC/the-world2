from __future__ import annotations

import datetime as dt
import io
import urllib.error
import urllib.request

import pytest

from senju.authorized_assessment import EngagementError, EngagementManifest
from senju.spear_web import AuthorizedWebPostureEngine


NOW = dt.datetime(2026, 8, 30, 14, 30, tzinfo=dt.timezone.utc)
PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(self, status=200, body=b"ok", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def close(self):
        return None


def manifest(**overrides):
    raw = {
        "engagement_id": "SPEAR-WEB-CI-001",
        "owner": "example-owner",
        "authorization_reference": "signed-roe-001",
        "valid_from_utc": "2026-08-30T00:00:00Z",
        "valid_until_utc": "2026-08-31T00:00:00Z",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "root_snapshot", "security_txt", "robots_txt", "options"],
        "max_requests_per_target": 5,
        "max_rps": 2.0,
        "allow_http": False,
        "destructive": False,
    }
    raw.update(overrides)
    return EngagementManifest.from_dict(raw)


def test_web_posture_emits_header_cookie_cors_and_method_findings() -> None:
    seen: list[tuple[str, str]] = []

    def opener(req: urllib.request.Request, *, timeout: float):
        seen.append((req.get_method(), req.full_url))
        if req.get_method() == "GET" and req.full_url == "https://example.com/":
            return FakeResponse(
                200,
                b"root",
                {
                    "Server": "Example/1.2.3",
                    "Set-Cookie": "sid=abc; Path=/",
                },
            )
        if req.get_method() == "HEAD":
            return FakeResponse(200, b"", {})
        if req.get_method() == "OPTIONS":
            return FakeResponse(
                204,
                b"",
                {
                    "Access-Control-Allow-Origin": "https://senju.invalid",
                    "Allow": "GET, HEAD, OPTIONS, TRACE, PUT",
                },
            )
        if req.full_url.endswith("/.well-known/security.txt"):
            return FakeResponse(404, b"missing", {})
        if req.full_url.endswith("/robots.txt"):
            return FakeResponse(200, b"User-agent: *\nDisallow:\n", {})
        raise AssertionError(req.full_url)

    engine = AuthorizedWebPostureEngine(
        manifest(),
        "example.com",
        resolver=lambda host, port: (PUBLIC_IP,),
        opener=opener,
        sleeper=lambda _: None,
    )
    report = engine.run(now=NOW).to_dict()

    assert report["schema"] == "senju-spear-web-posture/v1"
    assert report["requests_used"] == 5
    assert report["target_host"] == "example.com"
    assert report["boundaries"]["methods"] == ["GET", "HEAD", "OPTIONS"]
    assert report["boundaries"]["exploit_delivery"] is False
    assert report["boundaries"]["destructive_requests"] is False

    keys = {item["key"] for item in report["findings"]}
    assert "hsts-missing" in keys
    assert "csp-missing" in keys
    assert "cookie-secure-missing" in keys
    assert "cookie-httponly-missing" in keys
    assert "cookie-samesite-missing" in keys
    assert "banner-server" in keys
    assert "cors-origin-reflection" in keys
    assert "dangerous-methods-advertised" in keys
    assert "security-txt-missing" in keys
    assert seen == [
        ("GET", "https://example.com/"),
        ("HEAD", "https://example.com/"),
        ("OPTIONS", "https://example.com/"),
        ("GET", "https://example.com/.well-known/security.txt"),
        ("GET", "https://example.com/robots.txt"),
    ]


def test_web_posture_detects_wildcard_credentialed_cors() -> None:
    calls = 0

    def opener(req: urllib.request.Request, *, timeout: float):
        nonlocal calls
        calls += 1
        if req.get_method() == "OPTIONS":
            return FakeResponse(
                204,
                b"",
                {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Credentials": "true",
                },
            )
        return FakeResponse(200, b"ok", {
            "Strict-Transport-Security": "max-age=31536000",
            "Content-Security-Policy": "default-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        })

    report = AuthorizedWebPostureEngine(
        manifest(max_requests_per_target=3),
        "example.com",
        resolver=lambda host, port: (PUBLIC_IP,),
        opener=opener,
        sleeper=lambda _: None,
    ).run(now=NOW).to_dict()

    keys = {item["key"] for item in report["findings"]}
    assert "cors-wildcard-credentials" in keys
    assert calls == 3


def test_web_posture_does_not_follow_cross_host_redirect() -> None:
    def opener(req: urllib.request.Request, *, timeout: float):
        if req.get_method() == "GET":
            raise urllib.error.HTTPError(
                req.full_url,
                302,
                "redirect",
                {"Location": "https://other.example/final"},
                io.BytesIO(b"redirect"),
            )
        return FakeResponse(200, b"", {})

    report = AuthorizedWebPostureEngine(
        manifest(max_requests_per_target=1),
        "example.com",
        resolver=lambda host, port: (PUBLIC_IP,),
        opener=opener,
        sleeper=lambda _: None,
    ).run(now=NOW).to_dict()

    keys = {item["key"] for item in report["findings"]}
    assert "cross-host-redirect" in keys
    assert report["requests_used"] == 1


def test_web_posture_rejects_unlisted_host_before_network() -> None:
    with pytest.raises(EngagementError, match="not part of engagement"):
        AuthorizedWebPostureEngine(manifest(), "other.example")


def test_web_posture_rejects_private_resolution() -> None:
    engine = AuthorizedWebPostureEngine(
        manifest(max_requests_per_target=1),
        "example.com",
        resolver=lambda host, port: (_ for _ in ()).throw(
            EngagementError("non-public address blocked for external SPEAR target example.com: 127.0.0.1")
        ),
        opener=lambda *args, **kwargs: FakeResponse(),
        sleeper=lambda _: None,
    )
    with pytest.raises(EngagementError, match="non-public address blocked"):
        engine.run(now=NOW)
