from __future__ import annotations

import json
from pathlib import Path

from engine.authority_fasttrack_grant_bridge import run_fasttrack_grant_bridge


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _owner_root(repo: Path) -> None:
    _write(
        repo / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "id": "owner-root",
                    "owner_authorization": "explicit",
                    "authorization_authority_root": True,
                    "host": "owner.example",
                    "base_url": "https://owner.example",
                }
            ]
        },
    )


def test_fasttrack_can_emit_real_reviewed_authority_for_new_host_inside_owner_root(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _owner_root(repo)
    _write(
        state / "authority_priority_review_queue.json",
        {
            "requests": [
                {
                    "host": "api.owner.example",
                    "url": "https://api.owner.example/v1",
                    "authority_transition_requested": True,
                }
            ]
        },
    )

    result = run_fasttrack_grant_bridge(state, repo_root=repo, now=1_000_000)
    assert result["issued_count"] == 1
    assert result["held_count"] == 0
    assert result["issued"][0]["authority_effect"] == "real_reviewed_operational_grant"
    assert set(result["issued"][0]["shared_with"]) == {"META", "X", "SENJU", "CHILD", "PR-ARMY", "AI"}

    grants = json.loads((state / "authority_reviewed_grants.json").read_text())
    grant = grants["hosts"]["api.owner.example"]
    assert grant["matched_explicit_root"] == "owner.example"
    assert grant["allowed_methods"] == ["GET", "HEAD"]
    assert grant["effect"] == "read_only"
    assert grant["credential_scope"] == "none"


def test_unrelated_third_party_fasttrack_does_not_emit_authority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _owner_root(repo)
    _write(
        state / "authority_priority_review_queue.json",
        {
            "requests": [
                {
                    "host": "unrelated.example",
                    "url": "https://unrelated.example/",
                    "authority_transition_requested": True,
                }
            ]
        },
    )

    result = run_fasttrack_grant_bridge(state, repo_root=repo, now=1_000_000)
    assert result["issued_count"] == 0
    assert result["held_count"] == 1
    assert result["held"][0]["reason"] == "no_independent_explicit_owner_root"
    grants = json.loads((state / "authority_reviewed_grants.json").read_text())
    assert grants["hosts"] == {}


def test_fasttrack_flag_alone_is_not_enough(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _owner_root(repo)
    _write(
        state / "authority_priority_review_queue.json",
        {
            "requests": [
                {
                    "host": "api.owner.example",
                    "url": "https://api.owner.example/",
                    "authority_transition_requested": False,
                }
            ]
        },
    )

    result = run_fasttrack_grant_bridge(state, repo_root=repo, now=1_000_000)
    assert result["issued_count"] == 0


def test_stale_prior_grant_outside_current_owner_roots_is_not_preserved(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _owner_root(repo)
    _write(
        state / "authority_reviewed_grants.json",
        {
            "schema": "meta-authority-reviewed-grants/v1",
            "hosts": {
                "old-third-party.example": {
                    "expires_at": 2_000_000,
                    "allowed_methods": ["GET"],
                    "credential_scope": "none",
                    "effect": "read_only",
                }
            },
        },
    )
    _write(state / "authority_priority_review_queue.json", {"requests": []})

    run_fasttrack_grant_bridge(state, repo_root=repo, now=1_000_000)
    grants = json.loads((state / "authority_reviewed_grants.json").read_text())
    assert "old-third-party.example" not in grants["hosts"]
