from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from senju.external import (
    ExternalContactClient,
    ExternalContactError,
    ExternalContactPolicy,
)


PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_2 = "1.1.1.1"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"provider-ok",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {"Content-Type": "text/plain"}
        self.closed = False

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def close(self) -> None:
        self.closed = True


def public_resolver(host: str, port: int) -> tuple[str, ...]:
    assert host == "example.com"
    assert port == 443
    return (PUBLIC_IP,)


def multi_resolver(host: str, port: int) -> tuple[str, ...]:
    assert port == 443
    if host == "example.com":
        return (PUBLIC_IP,)
    if host == "api.example.com":
        return (PUBLIC_IP_2,)
    raise AssertionError(host)


def redirect_error(url: str, location: str, status: int = 302) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url,
        status,
        "redirect",
        {"Location": location, "Content-Type": "text/plain"},
        io.BytesIO(b"redirect"),
    )


def test_external_contact_requires_explicit_host_allowlist() -> None:
    policy = ExternalContactPolicy.from_hosts([])
    client = ExternalContactClient(policy, resolver=public_resolver, opener=lambda *a, **k: FakeResponse())
    with pytest.raises(ExternalContactError, match="not explicitly allowlisted"):
        client.contact("https://example.com/")


def test_external_contact_blocks_private_or_metadata_resolution() -> None:
    policy = ExternalContactPolicy.from_hosts(["example.com"])
    client = ExternalContactClient(
        policy,
        resolver=lambda host, port: ("169.254.169.254",),
        opener=lambda *a, **k: FakeResponse(),
    )
    with pytest.raises(ExternalContactError, match="non-public address blocked"):
        client.contact("https://example.com/")


def test_external_contact_https_get_emits_v3_receipt_and_body() -> None:
    seen: dict[str, object] = {}

    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(
            status=200,
            body=b' {"provider":"ok"} ',
            headers={
                "Content-Type": "application/json",
                "ETag": '"abc"',
                "Last-Modified": "Sun, 30 Aug 2026 12:00:00 GMT",
            },
        )

    policy = ExternalContactPolicy.from_hosts(["example.com"], timeout_seconds=2.5)
    result = ExternalContactClient(policy, resolver=public_resolver, opener=opener).contact_with_body(
        "https://example.com/contact",
    )

    assert seen == {"method": "GET", "url": "https://example.com/contact", "timeout": 2.5}
    assert result.receipt.schema == "senju-external-contact/v3"
    assert result.receipt.host == "example.com"
    assert result.receipt.final_host == "example.com"
    assert result.receipt.final_url == "https://example.com/contact"
    assert result.receipt.contacted_hosts == ("example.com",)
    assert result.receipt.resolved_ips == (PUBLIC_IP,)
    assert result.receipt.status == 200
    assert result.receipt.provider_acknowledged is True
    assert result.receipt.attempt_count == 1
    assert result.receipt.redirect_count == 0
    assert result.receipt.etag == '"abc"'
    assert result.json() == {"provider": "ok"}
    assert len(result.receipt.response_sha256) == 64


def test_external_contact_write_methods_and_options_are_bounded(tmp_path) -> None:
    captured: list[tuple[str, bytes | None]] = []

    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        captured.append((req.get_method(), req.data))
        return FakeResponse(status=202, body=b"accepted")

    policy = ExternalContactPolicy.from_hosts(["example.com"])
    payload = b'{"event":"senju-contact"}'
    client = ExternalContactClient(policy, resolver=public_resolver, opener=opener)

    for method in ("POST", "PUT", "PATCH"):
        result = client.contact_with_body(
            "https://example.com/hook",
            method=method,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        assert result.receipt.status == 202
        assert result.receipt.provider_acknowledged is True
        assert result.body == b"accepted"

    options = client.contact_with_body("https://example.com/hook", method="OPTIONS")
    assert options.receipt.status == 202
    assert [method for method, _ in captured] == ["POST", "PUT", "PATCH", "OPTIONS"]
    assert captured[-1][1] is None

    receipt_out = tmp_path / "receipt.json"
    body_out = tmp_path / "response.bin"
    result.receipt.write(receipt_out)
    result.write_body(body_out)
    data = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert data["schema"] == "senju-external-contact/v3"
    assert data["url"] == "https://example.com/hook"
    assert body_out.read_bytes() == b"accepted"


def test_delete_requires_explicit_opt_in_then_works() -> None:
    blocked = ExternalContactClient(
        ExternalContactPolicy.from_hosts(["example.com"]),
        resolver=public_resolver,
        opener=lambda *a, **k: FakeResponse(status=204, body=b""),
    )
    with pytest.raises(ExternalContactError, match="explicit allow_delete"):
        blocked.contact("https://example.com/resource/1", method="DELETE")

    seen: list[str] = []

    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        seen.append(req.get_method())
        return FakeResponse(status=204, body=b"")

    allowed = ExternalContactClient(
        ExternalContactPolicy.from_hosts(["example.com"], allow_delete=True),
        resolver=public_resolver,
        opener=opener,
    )
    receipt = allowed.contact("https://example.com/resource/1", method="DELETE")
    assert receipt.status == 204
    assert seen == ["DELETE"]


def test_external_contact_retries_transient_transport_failure() -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError("temporary")
        return FakeResponse(status=200, body=b"recovered")

    policy = ExternalContactPolicy.from_hosts(["example.com"], retries=2)
    result = ExternalContactClient(
        policy,
        resolver=public_resolver,
        opener=flaky,
        sleeper=sleeps.append,
    ).contact_with_body("https://example.com/")

    assert attempts["count"] == 2
    assert result.receipt.attempt_count == 2
    assert result.body == b"recovered"
    assert sleeps == [policy.retry_backoff_seconds]


def test_redirect_following_revalidates_each_allowlisted_hop() -> None:
    calls: list[str] = []

    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        calls.append(req.full_url)
        if len(calls) == 1:
            raise redirect_error(req.full_url, "https://api.example.com/final")
        return FakeResponse(status=200, body=b"final")

    policy = ExternalContactPolicy.from_hosts(
        ["example.com", "api.example.com"],
        follow_redirects=True,
    )
    result = ExternalContactClient(policy, resolver=multi_resolver, opener=opener).contact_with_body(
        "https://example.com/start"
    )

    assert calls == ["https://example.com/start", "https://api.example.com/final"]
    assert result.receipt.final_url == "https://api.example.com/final"
    assert result.receipt.final_host == "api.example.com"
    assert result.receipt.contacted_hosts == ("example.com", "api.example.com")
    assert result.receipt.redirect_count == 1
    assert set(result.receipt.resolved_ips) == {PUBLIC_IP, PUBLIC_IP_2}


def test_redirect_to_unallowlisted_host_is_blocked() -> None:
    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        raise redirect_error(req.full_url, "https://evil.example.net/final")

    policy = ExternalContactPolicy.from_hosts(["example.com"], follow_redirects=True)
    client = ExternalContactClient(policy, resolver=public_resolver, opener=opener)
    with pytest.raises(ExternalContactError, match="not explicitly allowlisted"):
        client.contact("https://example.com/start")


def test_cross_host_redirect_strips_sensitive_headers() -> None:
    calls: list[dict[str, str]] = []

    def opener(req: urllib.request.Request, *, timeout: float) -> FakeResponse:
        calls.append({k.lower(): v for k, v in req.header_items()})
        if len(calls) == 1:
            raise redirect_error(req.full_url, "https://api.example.com/final", 307)
        return FakeResponse(status=200, body=b"final")

    policy = ExternalContactPolicy.from_hosts(
        ["example.com", "api.example.com"],
        follow_redirects=True,
    )
    client = ExternalContactClient(policy, resolver=multi_resolver, opener=opener)
    result = client.contact_with_body(
        "https://example.com/start",
        headers={"Authorization": "Bearer secret", "X-Trace": "abc"},
    )
    assert result.receipt.status == 200
    assert calls[0]["authorization"] == "Bearer secret"
    assert "authorization" not in calls[1]
    assert calls[1]["x-trace"] == "abc"


def test_external_contact_rejects_plain_http_by_default() -> None:
    policy = ExternalContactPolicy.from_hosts(["example.com"])
    client = ExternalContactClient(policy, resolver=public_resolver, opener=lambda *a, **k: FakeResponse())
    with pytest.raises(ExternalContactError, match="plain HTTP is disabled"):
        client.contact("http://example.com/")


def test_external_contact_blocks_caller_controlled_host_header() -> None:
    policy = ExternalContactPolicy.from_hosts(["example.com"])
    client = ExternalContactClient(policy, resolver=public_resolver, opener=lambda *a, **k: FakeResponse())
    with pytest.raises(ExternalContactError, match="caller-controlled header"):
        client.contact("https://example.com/", headers={"Host": "169.254.169.254"})
