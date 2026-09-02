"""Tests for Senju live unknown-site discovery autonomy loop and HTML evidence."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from senju.autonomy.discovery import AutonomyError, AutonomyLoop, AutonomyQueue, WorkItem
from senju.discovery import HTMLPassiveExtractor, parse_html_evidence, extract_security_headers
from senju.external import ContactReceipt, ContactResult, ExternalContactPolicy


def test_autonomy_queue_priority_and_scoring():
    queue = AutonomyQueue(max_host_budget=2)

    item1 = WorkItem(
        id="item-1",
        item_type="discovery",
        url="https://example.com/page1",
        novelty_score=0.9,
        expected_research_value=0.8,
    )
    item2 = WorkItem(
        id="item-2",
        item_type="discovery",
        url="https://example.org/page1",
        novelty_score=0.5,
        expected_research_value=0.5,
    )

    assert queue.enqueue(item1) is True
    assert queue.enqueue(item2) is True
    # Duplicate URL enqueue should return False
    assert queue.enqueue(item1) is False

    # First popped item should be higher score (example.com)
    next_item = queue.pop_next()
    assert next_item is not None
    assert next_item.id == "item-1"

    # Record failure on example.com and verify score penalty
    queue.record_outcome("https://example.com/page1", success=False)
    item1_retry = WorkItem(
        id="item-1-retry",
        item_type="discovery",
        url="https://example.com/page2",
        novelty_score=0.9,
        expected_research_value=0.8,
    )
    assert queue.score_item(item1_retry) < item1.score


def test_html_passive_extractor_and_evidence():
    html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Test Security Portal</title>
        <script src="/static/app.js"></script>
        <link rel="stylesheet" href="/static/style.css">
      </head>
      <body>
        <h1>Welcome</h1>
        <a href="/about">About Us</a>
        <a href="https://example.com/contact">Contact</a>
        <form action="/login" method="POST">
          <input type="text" name="username" />
          <input type="password" name="password" />
        </form>
      </body>
    </html>
    """

    receipt = ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-30T12:00:00Z",
        method="GET",
        requested_url="https://example.com",
        final_url="https://example.com",
        host="example.com",
        final_host="example.com",
        contacted_hosts=("example.com",),
        resolved_ips=("93.184.216.34",),
        status=200,
        provider_acknowledged=True,
        response_bytes=len(html),
        response_sha256="fakehash123",
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )

    evidence = parse_html_evidence(
        requested_url="https://example.com",
        receipt=receipt,
        html_content=html,
        selection_score=0.85,
        discovery_source="test_feed",
        commit_sha="testsha123",
        workflow_run_id="run456",
    )

    assert evidence["schema"] == "senju-discovery-evidence/v1"
    assert evidence["html"]["title"] == "Test Security Portal"
    assert evidence["html"]["form_count"] == 1
    assert len(evidence["discovered_candidates"]) == 2

    # Check passive observations separation
    confirmed_titles = [o["title"] for o in evidence["passive_observations"]]
    assert "Missing Strict-Transport-Security Header" in confirmed_titles
    assert "Password Form Detected" in confirmed_titles

    hypotheses_titles = [h["title"] for h in evidence["unverified_hypotheses"]]
    assert "Potential Authentication Endpoint" in hypotheses_titles


def test_unknown_third_party_write_method_refused():
    loop = AutonomyLoop(
        allow_hosts=["example.com"],
        authorized_write_hosts=[],  # No authorized write hosts
    )

    item = WorkItem(
        id="bad-write",
        item_type="discovery",
        url="https://example.com/api",
        method="POST",
    )

    with pytest.raises(AutonomyError, match="must be GET/HEAD only"):
        loop.execute_step(item)


def test_autonomy_loop_live_discovery_and_learning(tmp_path):
    html = """
    <html>
      <head><title>Discovery Target</title></head>
      <body>
        <a href="/next-page">Next Page</a>
      </body>
    </html>
    """

    receipt = ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-30T12:00:00Z",
        method="GET",
        requested_url="https://example.com",
        final_url="https://example.com",
        host="example.com",
        final_host="example.com",
        contacted_hosts=("example.com",),
        resolved_ips=("93.184.216.34",),
        status=200,
        provider_acknowledged=True,
        response_bytes=len(html),
        response_sha256="abcdef1234567890",
        content_type="text/html",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )

    mock_client = MagicMock()
    mock_client.contact_with_body.return_value = ContactResult(
        receipt=receipt, body=html.encode("utf-8")
    )

    loop = AutonomyLoop(
        allow_hosts=["example.com"],
        out_dir=tmp_path,
        client=mock_client,
    )

    seed_item = WorkItem(
        id="seed-1",
        item_type="discovery",
        url="https://example.com",
        method="GET",
        source="seed_feed",
    )
    loop.queue.enqueue(seed_item)

    popped = loop.queue.pop_next()
    assert popped is not None
    res = loop.execute_step(popped)

    assert res["success"] is True
    assert res["new_enqueued_candidates"] == 1

    # Check next candidate enqueued by Senju without human URL supply
    next_candidate = loop.queue.pop_next()
    assert next_candidate is not None
    assert next_candidate.url == "https://example.com/next-page"
    assert next_candidate.source == "link_from:https://example.com"


def test_canary_write_and_readback(tmp_path):
    receipt_write = ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-30T12:00:00Z",
        method="POST",
        requested_url="https://canary.example.com/write",
        final_url="https://canary.example.com/write",
        host="canary.example.com",
        final_host="canary.example.com",
        contacted_hosts=("canary.example.com",),
        resolved_ips=("93.184.216.35",),
        status=201,
        provider_acknowledged=True,
        response_bytes=15,
        response_sha256="112233445566",
        content_type="application/json",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )

    receipt_read = ContactReceipt(
        schema="senju-external-contact/v3",
        contacted_at_utc="2026-08-30T12:00:01Z",
        method="GET",
        requested_url="https://canary.example.com/write",
        final_url="https://canary.example.com/write",
        host="canary.example.com",
        final_host="canary.example.com",
        contacted_hosts=("canary.example.com",),
        resolved_ips=("93.184.216.35",),
        status=200,
        provider_acknowledged=True,
        response_bytes=25,
        response_sha256="665544332211",
        content_type="application/json",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )

    mock_client = MagicMock()
    mock_client.contact_with_body.side_effect = [
        ContactResult(receipt=receipt_write, body=b'{"written":true}'),
        ContactResult(receipt=receipt_read, body=b'{"written":true,"id":1}'),
    ]

    loop = AutonomyLoop(
        allow_hosts=["canary.example.com"],
        authorized_write_hosts=["canary.example.com"],
        out_dir=tmp_path,
        client=mock_client,
    )

    canary_item = WorkItem(
        id="canary-1",
        item_type="canary_write",
        url="https://canary.example.com/write",
        method="POST",
        payload={"json": {"data": "test_canary"}},
    )

    res = loop.execute_step(canary_item)
    assert res["success"] is True
    assert res["federation_report"]["success"] is True
    assert len(res["federation_report"]["steps"]) == 2
