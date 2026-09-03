from __future__ import annotations

import json
from pathlib import Path

from engine.bounded_owner_delegation import run_bounded_owner_delegation_loop


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    host = "kabeya-authorized-test-range.onrender.com"
    _write(
        state / "human_intent_decisions.json",
        {
            "decisions": [
                {
                    "host": host,
                    "url": f"https://{host}/inside",
                    "confidence": 0.95,
                    "likely_owner_intent": True,
                    "priority": "immediate_proposal",
                    "reasons": ["owner_context", "owner_supplied_matching_link"],
                },
                {
                    "host": "outside.example",
                    "url": "https://outside.example/new",
                    "confidence": 0.90,
                    "likely_owner_intent": True,
                    "priority": "immediate_proposal",
                    "reasons": ["prior_similarity:0.95", "owner_context"],
                },
            ]
        },
    )
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "host": host,
                    "url": f"https://{host}/inside",
                    "decision": "probationary_authorized",
                },
                {
                    "host": "outside.example",
                    "url": "https://outside.example/new",
                    "decision": "candidate_only",
                },
            ]
        },
    )
    _write(
        state / "discovery_authorized.json",
        {
            "hosts": {
                host: {
                    "authorization_basis": "trusted_root",
                    "authorization_reference": host,
                    "expires_at": 4_000_000_000,
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                }
            }
        },
    )
    _write(
        state / "discovery_action_queue.json",
        {
            "actions": [
                {
                    "target": host,
                    "status": "ready",
                    "capabilities": ["scan", "probe", "write", "mutation"],
                }
            ]
        },
    )
    return state


def test_inference_creates_proposal_but_not_new_owner_root(tmp_path: Path) -> None:
    state = _base_state(tmp_path)
    result = run_bounded_owner_delegation_loop(state)

    proposals = json.loads((state / "owner_authority_proposals.json").read_text(encoding="utf-8"))["proposals"]
    outside = next(row for row in proposals if row["host"] == "outside.example")

    assert outside["status"] == "needs_explicit_owner_authority"
    assert outside["proposal_effect"] == "proposal_only_no_new_owner_root"
    assert outside["may_mint_new_owner_root"] is False
    assert result["new_owner_root_from_inference"] is False


def test_existing_owner_grant_gets_recursive_scope_preserving_delegation(tmp_path: Path) -> None:
    state = _base_state(tmp_path)
    result = run_bounded_owner_delegation_loop(state)

    queue = json.loads((state / "owner_delegation_queue.json").read_text(encoding="utf-8"))["queue"]
    lineage = json.loads((state / "owner_delegation_lineage.json").read_text(encoding="utf-8"))["lineages"][0]

    assert result["delegation_count"] == 5
    assert result["max_lineage_depth"] == 5
    assert lineage["path"] == ["Owner", "META", "X", "SENJU", "CHILD", "AI"]
    assert lineage["recursive"] is True
    assert lineage["scope_preserving"] is True
    assert lineage["credential_inheritance"] is False

    for row in queue:
        assert row["target_host"] == "kabeya-authorized-test-range.onrender.com"
        assert set(row["allowed_methods"]) == {"GET", "HEAD"}
        assert set(row["capabilities"]) == {"scan", "probe", "write", "mutation"}
        assert row["credential_scope"] == "none"
        assert row["scope_relation"] == "equal_or_narrower_than_parent"
        assert row["may_create_new_owner_root"] is False
        assert row["spawn_spec"]["inherit_authority"] is True
        assert row["spawn_spec"]["persistent"] is True


def test_credential_bearing_grant_is_not_recursively_inherited(tmp_path: Path) -> None:
    state = _base_state(tmp_path)
    authorized = json.loads((state / "discovery_authorized.json").read_text(encoding="utf-8"))
    host = "kabeya-authorized-test-range.onrender.com"
    authorized["hosts"][host]["credential_scope"] = "prod-secret"
    _write(state / "discovery_authorized.json", authorized)

    result = run_bounded_owner_delegation_loop(state)
    queue = json.loads((state / "owner_delegation_queue.json").read_text(encoding="utf-8"))["queue"]

    assert result["delegation_count"] == 0
    assert result["credential_inheritance"] is False
    assert queue == []


def test_persistent_queue_keeps_original_created_at(tmp_path: Path) -> None:
    state = _base_state(tmp_path)
    run_bounded_owner_delegation_loop(state)
    queue_path = state / "owner_delegation_queue.json"
    first = json.loads(queue_path.read_text(encoding="utf-8"))
    first_created = {row["delegation_id"]: row["created_at"] for row in first["queue"]}
    for row in first["queue"]:
        row["created_at"] = 123
        row["attempt_count"] = 7
    _write(queue_path, first)

    run_bounded_owner_delegation_loop(state)
    second = json.loads(queue_path.read_text(encoding="utf-8"))

    assert second["queue"]
    for row in second["queue"]:
        assert row["created_at"] == 123
        assert row["attempt_count"] == 7
        assert row["delegation_id"] in first_created
