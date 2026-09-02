from __future__ import annotations

import hashlib
import types
import urllib.parse

from senju.authorized_range_closed_loop import (
    AdaptiveProbeScheduler,
    AuthorizedRangeClosedLoop,
    AuthorizedRangePolicy,
    FindingMemory,
    LoopLimits,
)


HOST = "kabeya-authorized-test-range.onrender.com"


def policy() -> AuthorizedRangePolicy:
    return AuthorizedRangePolicy.from_dict(
        {
            "scope_id": "kabeya-authorized-test-range",
            "domain_roots": [HOST],
            "allow_http": False,
            "max_rps": 5,
            "timeout_seconds": 15,
            "max_response_bytes": 1024 * 1024,
            "retries": 1,
            "follow_redirects": True,
            "max_redirects": 4,
            "recursive_same_origin": True,
        }
    )


def receipt(url: str, status: int, body: bytes):
    return types.SimpleNamespace(
        status=status,
        response_sha256=hashlib.sha256(body).hexdigest(),
        final_url=url,
    )


class FakeClient:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def contact_with_body(self, url: str, *, method: str = "GET", **kwargs):
        self.seen.append((method, url))
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        if method == "OPTIONS":
            body = b""
            status = 204
        elif parsed.path == "/":
            canary = query.get("senju_probe", [""])[0]
            reflected = f"<p>{canary}</p>" if canary else ""
            body = (
                '<a href="/alpha">alpha</a>'
                '<a href="https://external.example/leave">external</a>'
                '<form method="POST" action="/submit"><input name="name"></form>'
                + reflected
            ).encode()
            status = 200
        elif parsed.path == "/alpha":
            body = b'<a href="/beta">beta</a>'
            status = 200
        elif parsed.path == "/beta":
            body = b"done"
            status = 200
        else:
            body = b"missing"
            status = 404
        return types.SimpleNamespace(receipt=receipt(url, status, body), body=body)


def test_exact_origin_normalization_blocks_other_hosts() -> None:
    p = policy()
    assert p.normalize_url("/alpha", base=f"https://{HOST}/") == f"https://{HOST}/alpha"
    assert p.normalize_url("https://external.example/nope") is None
    assert p.normalize_url(f"http://{HOST}/nope") is None


def test_finding_memory_deduplicates_and_confirms() -> None:
    memory = FindingMemory()
    first, is_new = memory.observe(
        category="input_reflection",
        url=f"https://{HOST}/",
        severity="info",
        confidence=0.7,
        evidence={"parameter": "q"},
        cycle=1,
        discriminator="q",
    )
    again, is_new_again = memory.observe(
        category="input_reflection",
        url=f"https://{HOST}/",
        severity="info",
        confidence=0.9,
        evidence={"retested": True},
        cycle=2,
        discriminator="q",
    )
    assert is_new is True
    assert is_new_again is False
    assert first.fingerprint == again.fingerprint
    assert again.status == "confirmed"
    assert again.observations == 2
    assert again.confidence == 0.9


def test_scheduler_learns_high_yield_family_after_equal_exploration() -> None:
    scheduler = AdaptiveProbeScheduler()
    for _ in range(4):
        for family in scheduler.FAMILIES:
            scheduler.record(
                family,
                new_findings=1 if family == "reflection_canary" else 0,
            )
    ranking = scheduler.rank()
    assert ranking[0] == "reflection_canary"
    snapshot = scheduler.snapshot()
    assert snapshot["reflection_canary"]["yield_rate"] == 1.0
    assert snapshot["content_map"]["yield_rate"] == 0.0


def test_closed_loop_crawls_internal_links_blocks_external_and_shares_findings() -> None:
    fake = FakeClient()

    def factory(transport_policy):
        assert transport_policy.allow_hosts == frozenset({HOST})
        assert transport_policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
        assert transport_policy.allow_delete is False
        return fake

    loop = AuthorizedRangeClosedLoop(
        policy(),
        limits=LoopLimits(
            max_cycles=3,
            max_pages=10,
            max_depth=3,
            max_requests=60,
            families_per_page=4,
            stagnant_cycles_to_stop=3,
        ),
        client_factory=factory,
        sleeper=lambda _: None,
    )
    report = loop.run()

    contacted_urls = [url for _, url in fake.seen]
    assert any(urllib.parse.urlsplit(url).path == "/alpha" for url in contacted_urls)
    assert any(urllib.parse.urlsplit(url).path == "/beta" for url in contacted_urls)
    assert all((urllib.parse.urlsplit(url).hostname or "") == HOST for url in contacted_urls)
    assert report["blocked_out_of_scope"] >= 1
    assert report["same_origin_only"] is True
    assert report["destructive"] is False
    assert report["request_count"] <= report["request_budget"]

    categories = {item["category"] for item in report["findings"]}
    assert "input_reflection" in categories
    assert "state_form_without_visible_csrf_hint" in categories
    assert report["finding_shares"]
    assert all(item["schema"] == "senju-finding-share/v2" for item in report["finding_shares"])
