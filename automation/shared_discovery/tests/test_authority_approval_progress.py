from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_progress import run_approval_progress


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _packet(host: str) -> dict:
    return {
        "packet_id": f"packet:{host}",
        "submission_id": f"submission:{host}",
        "host": host,
        "formal_intake": True,
        "attempt_count": 3,
        "readiness_score": 80,
        "secondary_validation": {"present": False},
        "authority_effect": "none",
        "authority_activated": False,
    }


def _repo(root: Path, hosts: list[str]) -> None:
    _write(root / "AUTHORIZED_TEST_TARGETS.json", {
        "targets": [
            {"host": host, "owner_authorization": "explicit"}
            for host in hosts
        ]
    })


def test_explicit_owner_host_collapses_intake_to_activation_and_has_progress_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    _repo(repo, ["owned.example.com"])
    _write(state / "formal_root_authority_approval_queue.json", {
        "candidates": [_packet("owned.example.com")]
    })

    result = run_approval_progress(state, repo_root=repo, now=2000)
    assert result["activated_count"] == 1

    doc = json.loads((state / "authority_approval_progress_state.json").read_text())
    row = doc["cases"][0]
    assert row["approval_coordinator"] == "META"
    assert row["review_evidence_complete"] is True
    assert row["current_stage"] == "authority_activated"
    assert row["blocking_reason"] is None
    assert row["missing_evidence"] == []
    assert row["next_action"] == "META_publish_activation_receipt"
    assert row["last_progress_at"] == 2000
    assert row["intake_admitted"] is True
    assert row["authority_activated"] is True
    assert row["authority_effect"] == "existing_explicit_owner_scope"


def test_unknown_host_uses_negotiation_packet_for_review_but_not_for_external_authority(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    _repo(repo, [])
    _write(state / "formal_root_authority_approval_queue.json", {
        "candidates": [_packet("unknown.example.net")]
    })

    run_approval_progress(state, repo_root=repo, now=2000)
    row = json.loads((state / "authority_approval_progress_state.json").read_text())["cases"][0]
    assert row["review_evidence_complete"] is True
    assert row["negotiation_evidence"]["accepted_for_governance_review"] is True
    assert row["negotiation_evidence"]["accepted_as_external_authorization"] is False
    assert row["current_stage"] == "executive_review"
    assert row["blocking_reason"] == "awaiting_META_X_SENJU_3_of_3"
    assert row["authority_activated"] is False


def test_exec_and_parliament_cannot_activate_unknown_host_without_explicit_authorization(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    _repo(repo, [])
    _write(state / "formal_root_authority_approval_queue.json", {
        "candidates": [_packet("reviewed.example.net")]
    })
    _write(state / "executive_council_decisions.json", {
        "decisions": [{
            "host": "reviewed.example.net",
            "approved": True,
            "approved_by": ["META", "X", "SENJU"],
        }]
    })
    _write(state / "parliamentary_authority_decisions.json", {
        "decisions": [{
            "host": "reviewed.example.net",
            "approved": True,
        }]
    })

    run_approval_progress(state, repo_root=repo, now=2000)
    row = json.loads((state / "authority_approval_progress_state.json").read_text())["cases"][0]
    assert row["executive_approved"] is True
    assert row["parliament_approved"] is True
    assert row["current_stage"] == "activation_blocked"
    assert row["blocking_reason"] == "explicit_authorization_required_for_activation"
    assert row["missing_evidence"] == ["explicit_owner_authorization"]
    assert row["authority_activated"] is False


def test_terminal_stop_always_wins_even_for_explicit_owner_host(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    _repo(repo, ["owned.example.com"])
    packet = _packet("owned.example.com")
    packet["revoked"] = True
    _write(state / "formal_root_authority_approval_queue.json", {"candidates": [packet]})

    run_approval_progress(state, repo_root=repo, now=2000)
    row = json.loads((state / "authority_approval_progress_state.json").read_text())["cases"][0]
    assert row["current_stage"] == "terminal_stop"
    assert row["authority_activated"] is False
    assert row["next_action"] == "none"


def test_last_progress_at_only_changes_when_stage_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    _repo(repo, [])
    _write(state / "formal_root_authority_approval_queue.json", {
        "candidates": [_packet("unknown.example.net")]
    })

    run_approval_progress(state, repo_root=repo, now=2000)
    run_approval_progress(state, repo_root=repo, now=3000)
    row = json.loads((state / "authority_approval_progress_state.json").read_text())["cases"][0]
    assert row["last_progress_at"] == 2000

    _write(state / "executive_council_decisions.json", {
        "decisions": [{
            "host": "unknown.example.net",
            "approved": True,
            "approved_by": ["META", "X", "SENJU"],
        }]
    })
    run_approval_progress(state, repo_root=repo, now=4000)
    row = json.loads((state / "authority_approval_progress_state.json").read_text())["cases"][0]
    assert row["current_stage"] == "parliamentary_review"
    assert row["last_progress_at"] == 4000
