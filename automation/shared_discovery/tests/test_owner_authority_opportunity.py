from __future__ import annotations

import json
from pathlib import Path

from engine.bounded_owner_delegation import run_bounded_owner_delegation_loop
from engine.owner_authority_opportunity import run_owner_authority_opportunity_loop


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_state(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state"
    state.mkdir()
    repo = tmp_path / "repo"
    (repo / "senju" / "state").mkdir(parents=True)
    host = "outside.example"
    url = f"https://{host}/new"
    _write(
        state / "human_intent_decisions.json",
        {
            "decisions": [
                {
                    "host": host,
                    "url": url,
                    "confidence": 0.91,
                    "likely_owner_intent": True,
                    "priority": "immediate_proposal",
                    "reasons": [
                        "owner_context",
                        "prior_similarity:0.95",
                        "prior_explicit_approval_exists",
                    ],
                }
            ]
        },
    )
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "host": host,
                    "url": url,
                    "decision": "candidate_only",
                    "reason": "outside_authorized_scope",
                }
            ]
        },
    )
    _write(state / "discovery_policy.json", {"trusted_roots": [], "company_domains": []})
    _write(state / "authority_reviewed_grants.json", {"schema": "meta-authority-reviewed-grants/v1", "hosts": {}})
    _write(state / "human_intent_signals.json", {"supplied_links": [], "owner_context": True})
    _write(state / "discovery_authorized.json", {"hosts": {}})
    _write(state / "discovery_action_queue.json", {"actions": []})
    return state, repo


def test_inference_only_gets_persistent_opportunity_not_owner_root(tmp_path: Path) -> None:
    state, repo = _base_state(tmp_path)

    result = run_owner_authority_opportunity_loop(state, repo_root=repo)
    doc = json.loads((state / "owner_authority_opportunity_queue.json").read_text(encoding="utf-8"))
    row = doc["opportunities"][0]

    assert result["opportunity_count"] == 1
    assert result["searching_count"] == 1
    assert result["authority_found_count"] == 0
    assert result["new_owner_root_from_inference"] is False
    assert row["status"] == "searching"
    assert row["attempt_count"] == 1
    assert row["may_mint_new_owner_root_from_inference"] is False
    assert row["recursive_delegation_ready"] is False
    assert row["curiosity_slot"]["effect"] == "search_order_only_never_authorization"
    assert row["signals"]["similarity_signal"] is True
    assert row["signals"]["historical_approval_signal"] is True
    assert row["signals"]["owner_context_signal"] is True


def test_opportunity_persists_and_rotates_search_strategy(tmp_path: Path) -> None:
    state, repo = _base_state(tmp_path)

    run_owner_authority_opportunity_loop(state, repo_root=repo)
    queue_path = state / "owner_authority_opportunity_queue.json"
    first = json.loads(queue_path.read_text(encoding="utf-8"))
    first_row = first["opportunities"][0]
    first_seen = first_row["first_seen_at"]
    first_strategy = first_row["current_strategy"]

    second_result = run_owner_authority_opportunity_loop(state, repo_root=repo)
    second = json.loads(queue_path.read_text(encoding="utf-8"))
    second_row = second["opportunities"][0]

    assert second_result["total_attempt_count"] == 2
    assert second_row["attempt_count"] == 2
    assert second_row["first_seen_at"] == first_seen
    assert second_row["current_strategy"] != first_strategy
    assert second_row["status"] == "searching"


def test_independent_owner_supplied_exact_link_is_detected_as_proof(tmp_path: Path) -> None:
    state, repo = _base_state(tmp_path)
    _write(
        state / "human_intent_signals.json",
        {
            "supplied_links": ["https://outside.example/new"],
            "owner_context": True,
        },
    )

    result = run_owner_authority_opportunity_loop(state, repo_root=repo)
    row = json.loads((state / "owner_authority_opportunity_queue.json").read_text(encoding="utf-8"))["opportunities"][0]

    assert result["authority_found_count"] == 1
    assert row["status"] == "authority_found"
    assert row["independent_authority_proof"]["basis"] == ["owner_supplied_exact_host", "outside.example"]
    # Proof discovery does not itself manufacture a live grant. Production discovery
    # authorization is still the component that materializes the grant.
    assert row["recursive_delegation_ready"] is False
    assert row["may_mint_new_owner_root_from_inference"] is False


def test_live_grant_unlocks_existing_recursive_delegation_without_credentials(tmp_path: Path) -> None:
    state, repo = _base_state(tmp_path)
    host = "outside.example"
    _write(
        state / "discovery_authorized.json",
        {
            "hosts": {
                host: {
                    "authorization_basis": "reviewed_explicit_exact_host",
                    "authorization_reference": "review:outside-example",
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

    opportunity = run_owner_authority_opportunity_loop(state, repo_root=repo)
    delegation = run_bounded_owner_delegation_loop(state)
    row = json.loads((state / "owner_authority_opportunity_queue.json").read_text(encoding="utf-8"))["opportunities"][0]

    assert opportunity["delegation_ready_count"] == 1
    assert row["recursive_delegation_ready"] is True
    assert row["live_authorization_reference"] == "review:outside-example"
    assert row["credential_inheritance"] is False
    assert delegation["delegation_count"] == 5
    assert delegation["credential_inheritance"] is False
