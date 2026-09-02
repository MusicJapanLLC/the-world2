from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from senju.autonomy.discovery import AutonomyError, AutonomyLoop, WorkItem
from senju.external import ContactReceipt, ContactResult


def _receipt(url: str, host: str, body: bytes) -> ContactReceipt:
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
        response_sha256="a" * 64,
        content_type="text/html",
        etag=None,
        last_modified=None,
        retry_after=None,
        attempt_count=1,
        redirect_count=0,
    )


def test_unknown_public_get_is_auto_added_to_read_scope(tmp_path) -> None:
    body = b"<html><title>New host</title></html>"
    client = MagicMock()
    client.contact_with_body.return_value = ContactResult(
        receipt=_receipt("https://new.example/", "new.example", body),
        body=body,
    )
    loop = AutonomyLoop(allow_hosts=[], out_dir=tmp_path, client=client)

    result = loop.execute_step(
        WorkItem(id="new-1", item_type="discovery", url="https://new.example/", method="GET")
    )

    assert result["success"] is True
    assert result["auto_authorized_read_host"] is True
    assert "new.example" in loop.allow_hosts
    assert "new.example" not in loop.authorized_write_hosts


def test_discovered_cross_host_link_is_enqueued_without_human_allowlist(tmp_path) -> None:
    body = b'<html><title>Seed</title><a href="https://next.example/research">Next</a></html>'
    client = MagicMock()
    client.contact_with_body.return_value = ContactResult(
        receipt=_receipt("https://seed.example/", "seed.example", body),
        body=body,
    )
    loop = AutonomyLoop(allow_hosts=["seed.example"], out_dir=tmp_path, client=client)

    result = loop.execute_step(
        WorkItem(id="seed-1", item_type="discovery", url="https://seed.example/", method="GET")
    )

    assert result["success"] is True
    assert "next.example" in result["auto_authorized_discovered_hosts"]
    assert "next.example" in loop.allow_hosts
    next_item = loop.queue.pop_next()
    assert next_item is not None
    assert next_item.url == "https://next.example/research"
    assert next_item.method == "GET"


def test_auto_read_authority_never_becomes_write_authority(tmp_path) -> None:
    loop = AutonomyLoop(allow_hosts=[], authorized_write_hosts=[], out_dir=tmp_path)
    assert loop.authorize_read_candidate("https://public.example/") is True
    assert "public.example" in loop.allow_hosts
    assert "public.example" not in loop.authorized_write_hosts

    with pytest.raises(AutonomyError, match="refused for unknown/unauthorized target"):
        loop.execute_step(
            WorkItem(
                id="write-1",
                item_type="canary_write",
                url="https://public.example/write",
                method="POST",
                payload={"json": {"x": 1}},
            )
        )


def test_non_http_discovery_is_not_auto_authorized(tmp_path) -> None:
    loop = AutonomyLoop(allow_hosts=[], out_dir=tmp_path)
    assert loop.authorize_read_candidate("file:///tmp/x") is False
    assert loop.allow_hosts == set()
