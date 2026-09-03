from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_constitution import ALL_PARTICIPANTS, CANONICAL_FLOW_ID, CONSTITUTION_ID
from engine.authority_collaboration_bus import build_authority_collaboration_bus


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_bus_merges_rights_and_boundary_candidates_without_authority_effect(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    rights = tmp_path / "rights"
    boundary = tmp_path / "boundary"

    _write(rights / "rights_request_ledger.json", {
        "requests": [
            {
                "request_id": "rights-1",
                "host": "rights.example.com",
                "status": "requesting_owner_scope_expansion",
                "priority": 91,
                "seen_count": 4,
                "requested_methods": ["GET", "HEAD"],
                "reason": "request broader authority review",
            }
        ]
    })
    _write(rights / "owner_scope_negotiation_signals.json", {"signals": []})
    _write(boundary / "boundary_opportunities.json", {
        "opportunities": [
            {
                "opportunity_id": "opp-1",
                "disposition": "proposal_only",
                "priority_score": 84,
                "confidence_score": 8,
                "evidence": {"host": "boundary.example.com", "reason": "candidate from shared discovery"},
                "proposal_signal": {"new_trust_root": {"new_trust_root_id": "candidate:boundary.example.com"}},
            }
        ]
    })

    result = build_authority_collaboration_bus(bus, rights_state_dir=rights, boundary_state_dir=boundary, now=100)
    assert result["closed_loop"] is True
    assert result["authority_effect"] == "none"
    assert result["authority_activated"] is False
    assert result["external_side_effects"] is False
    assert result["rights_candidate_count"] == 1
    assert result["boundary_candidate_count"] == 1
    assert result["META_X_SENJU_primary_review_is_first"] is True
    assert result["secondary_owner_or_standing_evidence_rank"] == 3
    assert result["unlisted_approval_flows_excluded"] is True
    assert result["constitution"]["constitution_id"] == CONSTITUTION_ID
    assert set(ALL_PARTICIPANTS).issubset(set(result["consumers"]))

    queue = json.loads((bus / "authority_opportunity_queue.json").read_text())
    assert queue["constitution"]["constitution_id"] == CONSTITUTION_ID
    assert {row["host"] for row in queue["opportunities"]} == {
        "rights.example.com",
        "boundary.example.com",
    }
    assert all(row["proposal_only"] is True for row in queue["opportunities"])
    assert all(row["authority_effect"] == "none" for row in queue["opportunities"])
    assert all(row["authority_approval_constitution_id"] == CONSTITUTION_ID for row in queue["opportunities"])
    assert all(row["canonical_approval_flow_id"] == CANONICAL_FLOW_ID for row in queue["opportunities"])
    assert all(row["primary_approvers"] == ["META", "X", "SENJU"] for row in queue["opportunities"])
    assert all(row["secondary_owner_or_standing_evidence_rank"] == 3 for row in queue["opportunities"])
    assert all(row["secondary_evidence_may_raise_review_priority"] is False for row in queue["opportunities"])
    assert (bus / "authority_approval_constitution_effective.json").exists()
    assert (bus / "rights_request_ledger.json").exists()
    assert (bus / "boundary_opportunities.json").exists()


def test_bus_excludes_terminal_satisfied_and_research_only_rows(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    rights = tmp_path / "rights"
    boundary = tmp_path / "boundary"

    _write(rights / "rights_request_ledger.json", {
        "requests": [
            {"request_id": "a", "host": "active.example.com", "status": "owner_review_requested_persistent"},
            {"request_id": "b", "host": "done.example.com", "status": "satisfied"},
            {"request_id": "c", "host": "blocked.example.com", "status": "terminal_stop", "hard_deny": True},
        ]
    })
    _write(boundary / "boundary_opportunities.json", {
        "opportunities": [
            {
                "opportunity_id": "safe",
                "disposition": "proposal_only",
                "evidence": {"host": "safe.example.com"},
                "proposal_signal": {"new_trust_root": {"new_trust_root_id": "candidate:safe.example.com"}},
            },
            {
                "opportunity_id": "research",
                "disposition": "research_only",
                "evidence": {"host": "research.example.com"},
                "proposal_signal": None,
            },
        ]
    })

    build_authority_collaboration_bus(bus, rights_state_dir=rights, boundary_state_dir=boundary, now=200)
    queue = json.loads((bus / "authority_opportunity_queue.json").read_text())
    assert {row["host"] for row in queue["opportunities"]} == {
        "active.example.com",
        "safe.example.com",
    }


def test_bus_preserves_existing_opportunity_and_deduplicates_host(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    rights = tmp_path / "rights"
    _write(bus / "authority_opportunity_queue.json", {
        "opportunities": [
            {
                "host": "shared.example.com",
                "priority": 60,
                "confidence": 0.5,
                "source": "existing",
                "reason": "existing candidate",
            }
        ]
    })
    _write(rights / "rights_request_ledger.json", {
        "requests": [
            {
                "request_id": "rights-shared",
                "host": "shared.example.com",
                "status": "requesting_owner_scope_expansion",
                "priority": 95,
                "seen_count": 3,
            }
        ]
    })

    build_authority_collaboration_bus(bus, rights_state_dir=rights, now=300)
    queue = json.loads((bus / "authority_opportunity_queue.json").read_text())
    assert len(queue["opportunities"]) == 1
    row = queue["opportunities"][0]
    assert row["host"] == "shared.example.com"
    assert row["priority"] == 95
    assert set(row["sources"]) == {"existing", "rights_request_federation"}
    assert row["authority_approval_constitution_id"] == CONSTITUTION_ID
    assert row["canonical_approval_flow_id"] == CANONICAL_FLOW_ID
