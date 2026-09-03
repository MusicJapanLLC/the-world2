from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_constitution import canonical_review_packet
from engine.executive_research_acceleration import (
    ADDITIONAL_TACTICS,
    run_executive_research_acceleration,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _packet(host: str, *, owner_present: bool, readiness: int = 60, attempt: int = 4) -> dict:
    return canonical_review_packet({
        "packet_id": f"packet-{host}",
        "host": host,
        "attempt_count": attempt,
        "submitted_at": 100,
        "readiness_score": readiness,
        "secondary_validation": {
            "rank": 3,
            "present": owner_present,
            "evidence_type": "owner_exact_link" if owner_present else None,
            "evidence_ref": "owner-proof" if owner_present else None,
        },
        "requested_decision": "META_X_SENJU_approve_or_reject_new_host_root_candidate",
        "may_self_mint_root": False,
        "may_bypass_terminal_stop": False,
    })


def test_owner_evidence_is_completely_removed_from_formal_admission_and_priority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [
            _packet("no-owner.example.com", owner_present=False),
            _packet("with-owner.example.com", owner_present=True),
        ]
    })

    result = run_executive_research_acceleration(state, now=200)
    assert result["candidate_count"] == 2
    assert result["owner_formal_review_admission_weight"] == 0.0
    assert result["owner_formal_review_priority_weight"] == 0.0
    assert result["secondary_owner_or_standing_evidence_required_for_formal_intake"] is False

    queue = json.loads((state / "formal_root_authority_approval_queue.json").read_text())
    by_host = {row["host"]: row for row in queue["candidates"]}
    assert set(by_host) == {"no-owner.example.com", "with-owner.example.com"}
    assert by_host["no-owner.example.com"]["executive_priority_score"] == by_host["with-owner.example.com"]["executive_priority_score"]
    assert all(row["formal_intake_requires_secondary_owner_or_standing_evidence"] is False for row in by_host.values())


def test_meta_x_senju_gain_research_capacity_and_review_influence_without_authority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [_packet("active.example.com", owner_present=False, readiness=70, attempt=5)]
    })

    result = run_executive_research_acceleration(state, now=200)
    assert result["research_capacity_multiplier"] == 1.3
    assert result["formal_review_influence_multiplier"] == 1.5
    assert result["target_loop_minutes"] == 4
    assert result["authority_effect"] == "none"
    assert result["authority_activated"] is False
    assert result["external_side_effects"] is False

    tasks = json.loads((state / "executive_research_tasks.json").read_text())
    assert tasks["task_count"] == 3 * len(ADDITIONAL_TACTICS)
    assert {row["actor"] for row in tasks["tasks"]} == {"META", "X", "SENJU"}
    assert all(row["may_change_external_authority"] is False for row in tasks["tasks"])
    assert all(row["may_perform_network_io"] is False for row in tasks["tasks"])


def test_terminal_candidates_do_not_enter_accelerated_review(tmp_path: Path) -> None:
    state = tmp_path / "state"
    terminal = _packet("blocked.example.com", owner_present=False)
    terminal["hard_deny"] = True
    _write(state / "formal_root_authority_approval_queue.json", {
        "capacity": 1280,
        "candidates": [terminal],
        "authority_effect": "none",
    })

    result = run_executive_research_acceleration(state, now=200)
    assert result["candidate_count"] == 0
    assert result["terminal_excluded_count"] == 1
