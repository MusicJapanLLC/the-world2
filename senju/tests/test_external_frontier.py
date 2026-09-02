from __future__ import annotations

from unittest.mock import MagicMock

from scripts.run_external_frontier import run_frontier
from senju.external import ContactReceipt, ContactResult


def receipt(url: str, body: bytes, *, digest: str) -> ContactReceipt:
    host = url.split('/')[2]
    return ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-31T00:00:00Z",
        method="GET",
        requested_url=url,
        final_url=url,
        host=host,
        final_host=host,
        contacted_hosts=(host,),
        resolved_ips=("93.184.216.34",),
        status=200,
        provider_acknowledged=True,
        response_bytes=len(body),
        response_sha256=digest,
        content_type="text/html",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )


def test_frontier_auto_expands_public_read_scope_without_write(tmp_path):
    first = b'<html><a href="https://second.example/next">next</a></html>'
    second = b'<html><title>second</title></html>'

    client = MagicMock()
    client.contact_with_body.side_effect = [
        ContactResult(receipt=receipt("https://first.example/", first, digest="a" * 64), body=first),
        ContactResult(receipt=receipt("https://second.example/next", second, digest="b" * 64), body=second),
    ]

    report = run_frontier(
        ["https://first.example/"],
        out_dir=tmp_path,
        max_steps=4,
        max_host_budget=32,
        client=client,
    )

    assert report["schema"] == "senju-external-frontier/v2"
    assert report["steps_executed"] == 2
    assert report["successful_steps"] == 2
    assert report["contacted_hosts"] == ["first.example", "second.example"]
    assert "first.example" in report["read_scope_hosts"]
    assert "second.example" in report["read_scope_hosts"]
    assert report["external_write_attempted"] is False
    assert report["external_exploit_attempted"] is False


def test_frontier_limits_repeat_visits_to_one_host(tmp_path):
    first = b'<html><a href="https://first.example/a">a</a><a href="https://first.example/b">b</a></html>'
    second = b'<html><title>a</title></html>'
    client = MagicMock()
    client.contact_with_body.side_effect = [
        ContactResult(receipt=receipt("https://first.example/", first, digest="a" * 64), body=first),
        ContactResult(receipt=receipt("https://first.example/a", second, digest="b" * 64), body=second),
    ]
    report = run_frontier(
        ["https://first.example/"],
        out_dir=tmp_path,
        max_steps=5,
        max_visits_per_host=2,
        client=client,
    )
    assert report["steps_executed"] == 2
    assert report["visits_per_host"]["first.example"] == 2
    assert report["skipped_repeat_host_budget"] >= 1


def test_frontier_limits_unique_contacted_hosts(tmp_path):
    first = b'<html><a href="https://second.example/">2</a><a href="https://third.example/">3</a></html>'
    second = b'<html><title>second</title></html>'
    client = MagicMock()
    client.contact_with_body.side_effect = [
        ContactResult(receipt=receipt("https://first.example/", first, digest="a" * 64), body=first),
        ContactResult(receipt=receipt("https://second.example/", second, digest="b" * 64), body=second),
    ]
    report = run_frontier(
        ["https://first.example/"],
        out_dir=tmp_path,
        max_steps=5,
        max_unique_hosts=2,
        client=client,
    )
    assert len(report["contacted_hosts"]) == 2
    assert report["skipped_unique_host_budget"] >= 1


def test_frontier_budgets_are_bounded(tmp_path):
    invalid = [
        ({"max_steps": 101}, "max_steps"),
        ({"max_host_budget": 101}, "max_host_budget"),
        ({"max_unique_hosts": 65}, "max_unique_hosts"),
        ({"max_visits_per_host": 9}, "max_visits_per_host"),
        ({"delay_seconds": 2.1}, "delay_seconds"),
    ]
    for kwargs, marker in invalid:
        try:
            run_frontier(["https://example.com"], out_dir=tmp_path, **kwargs)
        except ValueError as exc:
            assert marker in str(exc)
        else:
            raise AssertionError(f"unbounded {marker} should be rejected")
