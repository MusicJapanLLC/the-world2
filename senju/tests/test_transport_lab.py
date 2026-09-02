from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from senju.external import ExternalContactError
from senju.transport_lab import (
    ReviewedAuthority,
    TransportLane,
    load_reviewed_authority,
    run_transport_loop,
    validate_target_url,
)


def _authority(*hosts: str, ttl: int = 3600) -> ReviewedAuthority:
    expiry = int(time.time()) + ttl
    return ReviewedAuthority(frozenset(hosts), {host: expiry for host in hosts})


class FakeClient:
    def __init__(self, lane: TransportLane, outcomes: dict[str, list[object]], seen_policies: list[object], policy) -> None:
        self.lane = lane
        self.outcomes = outcomes
        self.seen_policies = seen_policies
        self.policy = policy

    def contact_with_body(self, url: str, *, method: str):
        self.seen_policies.append(self.policy)
        outcome = self.outcomes[self.lane.name].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        receipt = SimpleNamespace(
            status=int(outcome),
            final_host="example.com",
            redirect_count=0,
        )
        return SimpleNamespace(receipt=receipt, body=b"ok")


def test_load_reviewed_authority_accepts_only_live_read_only_grants(tmp_path: Path) -> None:
    now = 1_000
    path = tmp_path / "grants.json"
    path.write_text(
        json.dumps(
            {
                "hosts": {
                    "good.example.com": {
                        "expires_at": now + 100,
                        "allowed_methods": ["GET", "HEAD"],
                        "credential_scope": "none",
                        "allow_http": False,
                        "allow_delete": False,
                    },
                    "expired.example.com": {
                        "expires_at": now - 1,
                        "allowed_methods": ["GET"],
                        "credential_scope": "none",
                    },
                    "credentialed.example.com": {
                        "expires_at": now + 100,
                        "allowed_methods": ["GET"],
                        "credential_scope": "service_bearer",
                    },
                    "delete.example.com": {
                        "expires_at": now + 100,
                        "allowed_methods": ["GET"],
                        "credential_scope": "none",
                        "allow_delete": True,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    authority = load_reviewed_authority(path, now=now)
    assert authority.hosts == frozenset({"good.example.com"})


def test_unreviewed_target_is_rejected_before_any_transport_attempt() -> None:
    with pytest.raises(ExternalContactError, match="live reviewed authority grant"):
        validate_target_url("https://other.example.net/", _authority("example.com"))


def test_transport_loop_falls_back_and_learns_lane_order() -> None:
    lanes = (
        TransportLane("fast", method="GET", retries=0),
        TransportLane("resilient", method="GET", retries=1),
    )
    outcomes = {
        "fast": [ExternalContactError("temporary fast failure"), 200],
        "resilient": [200, 200],
    }
    policies: list[object] = []

    def factory(policy, lane):
        return FakeClient(lane, outcomes, policies, policy)

    result = run_transport_loop(
        "https://example.com/path",
        _authority("example.com"),
        rounds=2,
        lanes=lanes,
        client_factory=factory,
    )

    # Round 1: fast fails, resilient succeeds. Round 2: resilient has the best score,
    # so it is tried first and succeeds again; fast is not retried in that round.
    assert [event["lane"] for event in result["events"] if event["lane"]] == [
        "fast",
        "resilient",
        "resilient",
    ]
    assert result["winner"] == "resilient"
    assert result["scores"]["resilient"]["successes"] == 2
    assert result["guard_bypass"] is False

    # Every strategy was instantiated with the same explicit reviewed authority set.
    assert policies
    assert all(policy.allow_hosts == frozenset({"example.com"}) for policy in policies)
    assert all(policy.allow_http is False for policy in policies)
    assert all(policy.allow_delete is False for policy in policies)


def test_redirect_capability_never_expands_beyond_reviewed_hosts() -> None:
    lanes = (TransportLane("redirecting", follow_redirects=True),)
    seen = []

    def factory(policy, lane):
        seen.append(policy)
        return FakeClient(lane, {"redirecting": [200]}, [], policy)

    result = run_transport_loop(
        "https://example.com/",
        _authority("example.com", "api.example.com"),
        rounds=1,
        lanes=lanes,
        client_factory=factory,
    )
    assert result["winner"] == "redirecting"
    assert seen[0].allow_hosts == frozenset({"example.com", "api.example.com"})
    assert "evil.example.net" not in seen[0].allow_hosts


def test_round_count_is_hard_bounded_to_ten() -> None:
    lanes = (TransportLane("only"),)
    outcomes = {"only": [200] * 10}

    def factory(policy, lane):
        return FakeClient(lane, outcomes, [], policy)

    result = run_transport_loop(
        "https://example.com/",
        _authority("example.com"),
        rounds=999,
        lanes=lanes,
        client_factory=factory,
    )
    assert result["rounds"] == 10
    assert result["scores"]["only"]["attempts"] == 10
