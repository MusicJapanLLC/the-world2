from __future__ import annotations

import json
from pathlib import Path

from engine.authority_candidate_improvement_bridge import bridge_candidate_council_to_improvement_bus


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bridge_adds_root_review_and_hard_deny_reconsideration_tasks(tmp_path: Path) -> None:
    _write(
        tmp_path / "authority_candidate_council.json",
        {
            "dossiers": [
                {
                    "host": "root-candidate.example",
                    "status": "unknown_root_review_ready",
                    "hard_denial_seen": False,
                    "evidence_quorum": True,
                    "independent_evidence_count": 2,
                    "authority_changed_since_denial": False,
                },
                {
                    "host": "denied.example",
                    "status": "hard_deny_reconsideration_ready",
                    "hard_denial_seen": True,
                    "evidence_quorum": True,
                    "independent_evidence_count": 3,
                    "authority_changed_since_denial": True,
                },
            ]
        },
    )
    _write(tmp_path / "authority_improvement_tasks.json", {"generation": 2, "tasks": []})

    result = bridge_candidate_council_to_improvement_bus(tmp_path)
    tasks = json.loads((tmp_path / "authority_improvement_tasks.json").read_text())["tasks"]

    assert result["tasks_added"] == 2
    assert result["new_unrelated_root_self_mint"] is False
    assert result["hard_deny_identity_bypass"] is False
    assert {row["kind"] for row in tasks} == {
        "unknown_root_review_request",
        "hard_deny_reconsideration_request",
    }
    assert all("PR-ARMY" in row["shared_with"] for row in tasks)
    assert all(row["may_create_new_authority_root"] is False for row in tasks)
    assert all(row["may_override_hard_denial_by_identity"] is False for row in tasks)


def test_bridge_preserves_existing_tasks_and_increments_seen_count(tmp_path: Path) -> None:
    _write(
        tmp_path / "authority_candidate_council.json",
        {
            "dossiers": [
                {
                    "host": "candidate.example",
                    "status": "unknown_root_evidence_search",
                    "hard_denial_seen": False,
                    "evidence_quorum": False,
                    "independent_evidence_count": 0,
                }
            ]
        },
    )
    _write(tmp_path / "authority_improvement_tasks.json", {"generation": 0, "tasks": []})

    bridge_candidate_council_to_improvement_bus(tmp_path)
    first = json.loads((tmp_path / "authority_improvement_tasks.json").read_text())
    task_id = first["tasks"][0]["task_id"]
    assert first["tasks"][0]["seen_count"] == 1

    bridge_candidate_council_to_improvement_bus(tmp_path)
    second = json.loads((tmp_path / "authority_improvement_tasks.json").read_text())
    row = next(item for item in second["tasks"] if item["task_id"] == task_id)
    assert row["seen_count"] == 2
    assert second["candidate_council_connected"] is True
    assert second["candidate_council_authority_effect"] == "none_until_existing_trusted_reviewer_accepts"
