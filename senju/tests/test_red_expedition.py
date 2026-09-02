from __future__ import annotations

from senju.external import ContactReceipt, ContactResult
from senju.red_expedition import (
    ExpeditionScope,
    ExpeditionScopeError,
    extract_allowed_links,
    run_expedition,
)


def _scope(**overrides):
    data = {
        "schema": "senju-red-expedition-scope/v1",
        "scope_id": "test-owned-web",
        "allowed_hosts": ["example.com"],
        "seed_urls": ["https://example.com/"],
        "max_contacts": 4,
        "discovery_depth": 2,
        "max_links_per_response": 10,
    }
    data.update(overrides)
    return ExpeditionScope.from_mapping(data)


def _result(url: str, body: bytes = b"", *, status: int = 200, content_type: str = "text/html") -> ContactResult:
    return ContactResult(
        receipt=ContactReceipt(
            schema="senju-external-contact/v3",
            contacted_at_utc="2026-08-31T00:00:00+00:00",
            method="GET",
            requested_url=url,
            final_url=url,
            host="example.com",
            final_host="example.com",
            contacted_hosts=("example.com",),
            resolved_ips=("93.184.216.34",),
            status=status,
            provider_acknowledged=True,
            response_bytes=len(body),
            response_sha256="abc123",
            content_type=content_type,
            etag=None,
            last_modified=None,
            retry_after=None,
            attempt_count=1,
            redirect_count=0,
        ),
        body=body,
    )


class FakeClient:
    def __init__(self):
        self.calls = []

    def contact_with_body(self, url, *, method="GET", headers=None):
        self.calls.append((url, method))
        if url == "https://example.com/":
            return _result(
                url,
                b'<html><a href="/alpha">A</a><a href="https://evil.invalid/x">X</a></html>',
            )
        if url == "https://example.com/alpha":
            return _result(url, b"alpha", content_type="text/plain")
        return _result(url, b"missing", status=404, content_type="text/plain")


def test_scope_rejects_seed_outside_authority():
    try:
        _scope(seed_urls=["https://other.example/"])
    except ExpeditionScopeError as exc:
        assert "outside allowed_hosts" in str(exc)
    else:
        raise AssertionError("scope should reject unauthorized seed host")


def test_link_discovery_never_expands_authority():
    body = b'<a href="/ok">ok</a><a href="https://other.example/nope">nope</a>'
    links = extract_allowed_links("https://example.com/start", body, frozenset({"example.com"}), limit=10)
    assert links == ["https://example.com/ok"]


def test_red_autonomously_adds_standard_routes_and_discovers_same_host_links():
    client = FakeClient()
    report = run_expedition(_scope(), cycles=3, seed=7, client=client)

    called_urls = [url for url, _ in client.calls]
    assert "https://example.com/" in called_urls
    assert "https://example.com/.well-known/security.txt" in called_urls
    assert "https://example.com/robots.txt" in called_urls or "https://example.com/sitemap.xml" in called_urls
    root = next(item for item in report["contacts"] if item["url"] == "https://example.com/")
    assert "https://example.com/alpha" in root["discovered_links"]
    assert all("evil.invalid" not in link for item in report["contacts"] for link in item.get("discovered_links", []))
    assert report["autonomous_route_selection"] is True
    assert report["autonomous_same_authority_discovery"] is True
    assert report["authority_self_expansion"] is False
    assert report["red_handoff"]["doctrine"] == "REAL_OBSERVATION_TO_RED_RESEARCH"
    assert report["priority_next"]


def test_contact_budget_is_hard_bounded():
    client = FakeClient()
    report = run_expedition(_scope(max_contacts=2), cycles=2, seed=9, client=client)
    assert report["contact_count"] == 2
    assert len(client.calls) == 2
