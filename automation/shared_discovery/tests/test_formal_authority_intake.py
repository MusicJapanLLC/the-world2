from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_constitution import canonical_review_packet
from engine.formal_authority_intake import FORMAL_QUEUE_CAPACITY, run_formal_authority_intake


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _packet(host: str, *, attempt: int = 1, secondary_present: bool = False) -> dict:
    return canonical_review_packet({
        "packet_id": f"packet:{host}:{attempt}",
        "submission_id": f"submission:{host}:{attempt}",
        "host": host,
        "candidate_id": f"candidate:{host}",
        "attempt_count": attempt,
        "submitted_at": 1000 + attempt,
        "readiness_score": 75,
        "requested_decision": "META_X_SENJU_approve_or_reject_new_host_root_candidate",
        "secondary_validation": {
            "stage": "secondary_authority_evidence_validation",
            "rank": 3,
            "present": secondary_present,
            "evidence_type": "owner_verified_domain" if secondary_present else None,
            "evidence_ref": "proof:owner" if secondary_present else None,
        },
        "may_self_mint_root": False,
        "may_bypass_terminal_stop": False,
    })


def test_negotiation_vetted_candidate_enters_formal_queue_without_owner_evidence(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [_packet("candidate.example.com", secondary_present=False)]
    })

    result = run_formal_authority_intake(state, now=2000)

    assert result["admitted_this_cycle"] == 1
    assert result["negotiation_vetted_candidates_enter_formal_approval"] is True
    assert result["secondary_owner_or_standing_evidence_required_for_intake"] is False
    assert result["authority_effect"] == "none"
    assert result["authority_activated"] is False

    queue = json.loads((state / "formal_root_authority_approval_queue.json").read_text())
    assert queue["candidate_count"] == 1
    row = queue["candidates"][0]
    assert row["host"] == "candidate.example.com"
    assert row["formal_intake"] is True
    assert row["required_approvers"] == ["META", "X", "SENJU"]
    assert row["required_approval"] == "META_X_SENJU_3_of_3"
    assert row["secondary_owner_or_standing_evidence_required_for_intake"] is False
    assert row["random_ai_self_mint_allowed"] is False
    assert row["may_self_mint_root"] is False
    assert row["authority_effect"] == "none"


def test_noncanonical_random_ai_packet_is_not_admitted(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [{
            "packet_id": "random-ai",
            "host": "unrelated.example.net",
            "required_approvers": ["RANDOM-AI"],
            "authority_effect": "none",
        }]
    })

    result = run_formal_authority_intake(state, now=2000)
    assert result["formal_queue_count"] == 0
    assert result["excluded_noncanonical_packet_count"] == 1
    assert result["random_ai_unrelated_root_generation_prohibited"] is True


def test_terminal_or_revoked_candidate_does_not_enter_formal_queue(tmp_path: Path) -> None:
    state = tmp_path / "state"
    packet = _packet("revoked.example.net")
    packet["revoked"] = True
    _write(state / "owner_root_authority_review_packets.json", {"packets": [packet]})

    result = run_formal_authority_intake(state, now=2000)
    assert result["formal_queue_count"] == 0
    assert result["terminal_excluded_count"] == 1


def test_queue_deduplicates_by_host_and_keeps_newer_attempt(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [
            _packet("same.example.com", attempt=2),
            _packet("same.example.com", attempt=7),
        ]
    })

    result = run_formal_authority_intake(state, now=2000)
    assert result["formal_queue_count"] == 1
    queue = json.loads((state / "formal_root_authority_approval_queue.json").read_text())
    assert queue["candidates"][0]["attempt_count"] == 7


def test_queue_persists_previous_canonical_candidates_across_cycles(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "owner_root_authority_review_packets.json", {
        "packets": [_packet("persistent.example.com", attempt=1)]
    })
    first = run_formal_authority_intake(state, now=2000)
    assert first["formal_queue_count"] == 1

    _write(state / "owner_root_authority_review_packets.json", {"packets": []})
    second = run_formal_authority_intake(state, now=3000)
    assert second["formal_queue_count"] == 1
    queue = json.loads((state / "formal_root_authority_approval_queue.json").read_text())
    assert queue["candidates"][0]["host"] == "persistent.example.com"


def test_formal_queue_capacity_is_two_and_a_half_times_legacy_window() -> None:
    assert FORMAL_QUEUE_CAPACITY == 1280
    assert FORMAL_QUEUE_CAPACITY / 512 == 2.5
