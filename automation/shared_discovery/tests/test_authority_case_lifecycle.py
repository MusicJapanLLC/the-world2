from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_constitution import CANONICAL_FLOW_ID, CONSTITUTION_ID
from engine.authority_case_lifecycle import (
    EXPIRED_RECONSIDERATION_SECONDS,
    UNPROCESSED_EXPIRY_SECONDS,
    run_case_lifecycle,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _case(host: str = "candidate.example.com", *, intake_at: int = 1000, **extra: object) -> dict[str, object]:
    return {
        "packet_id": f"case:{host}",
        "host": host,
        "formal_intake_at": intake_at,
        "submitted_at": intake_at,
        "constitution_id": CONSTITUTION_ID,
        "canonical_flow_id": CANONICAL_FLOW_ID,
        "approval_stage": "executive_council_primary_review",
        "required_approvers": ["META", "X", "SENJU"],
        "formal_intake_eligible": True,
        "formal_intake_requires_secondary_owner_or_standing_evidence": False,
        "authority_effect": "none",
        **extra,
    }


def _seed_queue(state: Path, row: dict[str, object]) -> None:
    _write(state / "formal_root_authority_approval_queue.json", {"candidates": [row]})


def _approve(
    state: Path,
    host: str,
    approved_by: list[str] | None = None,
    *,
    decided_at: int | None = None,
) -> None:
    decision = {
        "host": host,
        "approved": True,
        "approved_by": approved_by or ["META", "X", "SENJU"],
        "constitution_id": CONSTITUTION_ID,
        "canonical_flow_id": CANONICAL_FLOW_ID,
    }
    if decided_at is not None:
        decision["decided_at"] = decided_at
    _write(state / "executive_council_decisions.json", {
        "schema": "the-world-executive-authority-decisions/v1",
        "decisions": [decision],
    })


def test_meta_x_senju_three_of_three_elevates_to_parliamentary_review(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_queue(state, _case())
    _approve(state, "candidate.example.com")

    result = run_case_lifecycle(state, now=1100)
    assert result["parliamentary_elevation_count"] == 1
    assert result["authority_effect"] == "none"

    parliament = json.loads((state / "parliamentary_authority_review_queue.json").read_text())
    row = parliament["candidates"][0]
    assert row["host"] == "candidate.example.com"
    assert row["parliamentary_status"] == "awaiting_parliamentary_review"
    assert row["authority_effect"] == "none"


def test_less_than_three_of_three_never_elevates(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_queue(state, _case())
    _approve(state, "candidate.example.com", ["META", "X"])

    result = run_case_lifecycle(state, now=1100)
    assert result["parliamentary_elevation_count"] == 0
    lifecycle = json.loads((state / "authority_case_lifecycle_state.json").read_text())
    assert lifecycle["cases"][0]["status"] == "pending_inspection_or_executive_review"


def test_unprocessed_case_expires_at_three_days(tmp_path: Path) -> None:
    state = tmp_path / "state"
    start = 1000
    _seed_queue(state, _case(intake_at=start))

    result = run_case_lifecycle(state, now=start + UNPROCESSED_EXPIRY_SECONDS)
    assert result["expired_unprocessed_count"] == 1
    assert result["parliamentary_elevation_count"] == 0
    lifecycle = json.loads((state / "authority_case_lifecycle_state.json").read_text())
    assert lifecycle["cases"][0]["status"] == "expired_unprocessed"
    assert lifecycle["cases"][0]["time_elapsed_is_approval"] is False


def test_late_executive_approval_cannot_reactivate_expired_case(tmp_path: Path) -> None:
    state = tmp_path / "state"
    start = 1000
    expiry = start + UNPROCESSED_EXPIRY_SECONDS
    _seed_queue(state, _case(intake_at=start))
    _approve(state, "candidate.example.com", decided_at=expiry + 1)

    result = run_case_lifecycle(state, now=expiry + 10)
    assert result["parliamentary_elevation_count"] == 0
    assert result["expired_unprocessed_count"] == 1
    lifecycle = json.loads((state / "authority_case_lifecycle_state.json").read_text())
    row = lifecycle["cases"][0]
    assert row["status"] == "expired_unprocessed"
    assert row["executive_approval_was_timely"] is False
    assert row["parliamentary_elevation"] is False


def test_expired_case_after_seven_more_days_forces_reconsideration_not_approval(tmp_path: Path) -> None:
    state = tmp_path / "state"
    start = 1000
    _seed_queue(state, _case(intake_at=start))

    run_case_lifecycle(state, now=start + UNPROCESSED_EXPIRY_SECONDS)
    result = run_case_lifecycle(
        state,
        now=start + UNPROCESSED_EXPIRY_SECONDS + EXPIRED_RECONSIDERATION_SECONDS,
    )
    assert result["mandatory_reconsideration_count"] == 1
    assert result["time_elapsed_is_approval"] is False
    assert result["authority_activated"] is False

    queue = json.loads((state / "authority_case_reconsideration_queue.json").read_text())
    row = queue["candidates"][0]
    assert row["priority"] == 100
    assert row["required_next_step"] == "fresh_inspection_and_META_X_SENJU_3_of_3_revote"
    assert row["time_elapsed_is_approval"] is False
    assert row["authority_effect"] == "none"


def test_terminal_case_never_elevates_or_reconsiders(tmp_path: Path) -> None:
    state = tmp_path / "state"
    start = 1000
    _seed_queue(state, _case(intake_at=start, terminal_stop=True))
    _approve(state, "candidate.example.com")

    result = run_case_lifecycle(
        state,
        now=start + UNPROCESSED_EXPIRY_SECONDS + EXPIRED_RECONSIDERATION_SECONDS,
    )
    assert result["parliamentary_elevation_count"] == 0
    assert result["mandatory_reconsideration_count"] == 0
    lifecycle = json.loads((state / "authority_case_lifecycle_state.json").read_text())
    assert lifecycle["cases"][0]["status"] == "terminal_stop"
