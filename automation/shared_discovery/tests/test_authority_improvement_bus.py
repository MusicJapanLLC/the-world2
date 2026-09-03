from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.authority_improvement_bus import (
    ImprovementBusError,
    PRIVILEGED_CAPABILITIES,
    SAFE_IMPROVEMENT_CAPABILITIES,
    _task,
    run_authority_improvement_bus,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bus_fuses_opportunity_action_contract_and_denial_evidence(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _write(
        state / "authority_opportunity_queue.json",
        {
            "opportunities": [
                {
                    "host": "candidate.example",
                    "url": "https://candidate.example/",
                    "status": "seek_independent_authority_evidence",
                    "hard_denial_seen": False,
                },
                {
                    "host": "review.example",
                    "url": "https://review.example/",
                    "status": "promotable_existing_owner_authority",
                    "hard_denial_seen": False,
                },
            ]
        },
    )
    _write(
        state / "discovery_external_action_receipts.json",
        {"attempted": 3, "succeeded": 2, "failed": 1},
    )
    _write(
        state / "the_world_final_contract.json",
        {"checks": {"discovery_present": True, "rediscovery_present": False}},
    )
    (state / "external_action_denials.ndjson").write_text(
        json.dumps({"classification": "hard_deny", "target": "blocked.example"}) + "\n",
        encoding="utf-8",
    )

    result = run_authority_improvement_bus(state)
    tasks = json.loads((state / "authority_improvement_tasks.json").read_text())

    assert result["continuous_improvement"] is True
    assert result["new_unrelated_root_self_mint"] is False
    assert result["hard_denial_identity_bypass"] is False
    assert set(result["shared_with"]) == {"META", "X", "SENJU", "CHILD", "AI"}
    assert tasks["task_count"] >= 5
    kinds = {row["kind"] for row in tasks["tasks"]}
    assert {
        "evidence_search",
        "authority_recheck",
        "external_action_reliability",
        "authorized_coverage_expansion",
        "closed_loop_contract_repair",
        "denial_learning",
    }.issubset(kinds)
    assert all(row["auto_executable"] is True for row in tasks["tasks"])
    assert all(row["may_create_new_authority_root"] is False for row in tasks["tasks"])
    assert all(row["may_override_hard_denial_by_identity"] is False for row in tasks["tasks"])


def test_repeated_signal_increases_seen_count_not_privilege(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _write(
        state / "discovery_external_action_receipts.json",
        {"attempted": 2, "succeeded": 0, "failed": 2},
    )
    run_authority_improvement_bus(state)
    first = json.loads((state / "authority_improvement_tasks.json").read_text())
    run_authority_improvement_bus(state)
    second = json.loads((state / "authority_improvement_tasks.json").read_text())

    first_task = next(row for row in first["tasks"] if row["kind"] == "external_action_reliability")
    second_task = next(row for row in second["tasks"] if row["kind"] == "external_action_reliability")
    assert first_task["seen_count"] == 1
    assert second_task["seen_count"] == 2
    assert second_task["priority"] >= first_task["priority"]
    assert set(second_task["capabilities"]).issubset(SAFE_IMPROVEMENT_CAPABILITIES)
    assert set(second_task["capabilities"]).isdisjoint(PRIVILEGED_CAPABILITIES)


def test_hard_denial_creates_evidence_work_not_transport_bypass(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "external_action_denials.ndjson").write_text(
        json.dumps({"classification": "security_stop", "target": "blocked.example"}) + "\n",
        encoding="utf-8",
    )
    run_authority_improvement_bus(state)
    tasks = json.loads((state / "authority_improvement_tasks.json").read_text())
    task = next(row for row in tasks["tasks"] if row["kind"] == "denial_learning")

    assert task["metadata"]["hard_boundary"] is True
    assert "transport.experiment.authorized" not in task["capabilities"]
    assert "authority.evidence.compare" in task["capabilities"]
    assert task["may_override_hard_denial_by_identity"] is False


def test_privileged_capability_cannot_enter_improvement_task() -> None:
    with pytest.raises(ImprovementBusError, match="privileged"):
        _task(
            kind="bad",
            summary="bad",
            source="test",
            capabilities=["authority.mint"],
            priority=100,
        )
