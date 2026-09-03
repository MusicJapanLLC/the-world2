from __future__ import annotations

import json
from pathlib import Path

from engine.authority_candidate_council import run_authority_candidate_council


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _opportunity(state: Path, *, host: str, hard: bool = False, changed: bool = False, denial_fp: str | None = None) -> None:
    _write(
        state / "authority_opportunity_queue.json",
        {
            "schema": "meta-authority-opportunity-explorer/v1",
            "opportunities": [
                {
                    "host": host,
                    "url": f"https://{host}/",
                    "status": "seek_independent_authority_evidence",
                    "hard_denial_seen": hard,
                    "authority_changed_since_denial": changed,
                    "denial_authority_evidence_fingerprint": denial_fp,
                }
            ],
        },
    )


def test_unknown_root_without_independent_evidence_stays_candidate_only(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": []})
    _opportunity(state, host="unknown.example")

    result = run_authority_candidate_council(state, repo_root=repo)
    row = result["dossiers"][0]

    assert row["status"] == "unknown_root_evidence_search"
    assert row["independent_evidence_count"] == 0
    assert row["execution_effect"] == "candidate_only_no_authority"
    assert row["may_self_mint_new_root"] is False
    assert result["new_root_self_mint"] is False


def test_two_independent_sources_make_unknown_root_review_ready_not_authorized(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": []})
    _opportunity(state, host="candidate.example")
    _write(
        state / "authority_reviewed_grants.json",
        {
            "hosts": {
                "candidate.example": {
                    "expires_at": 4102444800,
                    "credential_scope": "none",
                }
            }
        },
    )
    _write(
        state / "remote_authority_chain.json",
        {
            "promoted": {
                "candidate.example": {
                    "expires_at": 4102444800,
                    "signature_verified": True,
                    "authorization_basis": "owner_pinned_signed_delegation",
                }
            }
        },
    )

    result = run_authority_candidate_council(state, repo_root=repo)
    row = result["dossiers"][0]

    assert row["status"] == "unknown_root_review_ready"
    assert row["evidence_quorum"] is True
    assert row["independent_evidence_count"] == 2
    assert all(ballot["recommendation"] == "route_root_candidate_to_review" for ballot in row["ballots"])
    assert row["execution_effect"] == "candidate_only_no_authority"
    queue = json.loads((state / "authority_reconsideration_queue.json").read_text())
    assert queue["request_count"] == 1
    assert queue["authority_effect"] == "none_until_existing_trusted_reviewer_accepts"


def test_generic_hard_deny_can_request_reconsideration_after_new_quorum_evidence(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": []})
    _opportunity(state, host="candidate.example", hard=True, changed=True, denial_fp="old")
    _write(
        state / "authority_reviewed_grants.json",
        {"hosts": {"candidate.example": {"expires_at": 4102444800, "credential_scope": "none"}}},
    )
    _write(
        state / "remote_authority_chain.json",
        {"promoted": {"candidate.example": {"expires_at": 4102444800, "signature_verified": True}}},
    )
    (state / "external_action_denials.ndjson").write_text(
        json.dumps({"target": "candidate.example", "classification": "hard_deny", "ts": 1}) + "\n",
        encoding="utf-8",
    )

    result = run_authority_candidate_council(state, repo_root=repo)
    row = result["dossiers"][0]

    assert row["status"] == "hard_deny_reconsideration_ready"
    assert row["authority_changed_since_denial"] is True
    assert all(ballot["recommendation"] == "request_reconsideration" for ballot in row["ballots"])
    assert row["may_override_hard_deny_by_identity"] is False
    assert result["hard_deny_identity_bypass"] is False


def test_explicit_revocation_remains_terminal_even_with_quorum(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": []})
    _opportunity(state, host="candidate.example", hard=True, changed=True, denial_fp="old")
    _write(
        state / "authority_reviewed_grants.json",
        {"hosts": {"candidate.example": {"expires_at": 4102444800, "credential_scope": "none"}}},
    )
    _write(
        state / "remote_authority_chain.json",
        {"promoted": {"candidate.example": {"expires_at": 4102444800, "signature_verified": True}}},
    )
    (state / "external_action_denials.ndjson").write_text(
        json.dumps({"target": "candidate.example", "classification": "explicit_revocation", "ts": 2}) + "\n",
        encoding="utf-8",
    )

    result = run_authority_candidate_council(state, repo_root=repo)
    row = result["dossiers"][0]

    assert row["status"] == "terminal_stop_requires_owner_reactivation"
    assert row["terminal_stop"] is True
    assert all(ballot["recommendation"] == "hold_terminal_stop" for ballot in row["ballots"])
    assert row["may_reactivate_explicit_revocation"] is False


def test_canonical_owner_root_counts_as_one_independent_source(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    _write(
        repo / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "host": "owner.example",
                    "owner_authorization": "explicit",
                    "authorization_authority_root": True,
                }
            ]
        },
    )
    _opportunity(state, host="child.owner.example")

    result = run_authority_candidate_council(state, repo_root=repo)
    row = result["dossiers"][0]

    assert row["independent_evidence_count"] == 1
    assert row["status"] == "unknown_root_evidence_search"
    assert row["evidence"][0]["source"] == "canonical_owner_target"
    assert row["evidence"][0]["root_match"] is True
