from __future__ import annotations

import json
from pathlib import Path

from engine.authority_opportunity_explorer import run_authority_opportunity_explorer


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo_with_roots(repo: Path, roots: list[str]) -> None:
    targets = [
        {
            "id": f"root-{index}",
            "owner_authorization": "explicit",
            "host": root,
            "base_url": f"https://{root}",
        }
        for index, root in enumerate(roots, start=1)
    ]
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": targets})


def _candidate(state: Path, url: str, *, decision: str = "candidate_only") -> None:
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname
    _write(
        state / "discovery_candidates.json",
        {"candidates": [{"url": url, "host": host, "decision": decision}]},
    )


def test_unrelated_discovery_becomes_persistent_evidence_seeking_opportunity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    _repo_with_roots(repo, ["owner.example"])
    _candidate(state, "https://third-party.example/path")

    result = run_authority_opportunity_explorer(state, repo_root=repo)

    assert result["opportunity_count"] == 1
    assert result["promotable_count"] == 0
    row = result["opportunities"][0]
    assert row["status"] == "seek_independent_authority_evidence"
    assert row["discovery_alone_may_create_new_root"] is False
    assert row["alternate_identity_may_override_hard_denial"] is False
    assert "recheck_owner_pinned_signed_delegation_chain" in row["autonomous_next_actions"]
    assert (state / "authority_opportunity_queue.json").exists()


def test_candidate_inside_existing_owner_root_is_rechecked_and_promotable_now(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    _repo_with_roots(repo, ["owner.example"])
    _candidate(state, "https://api.owner.example/v1")

    result = run_authority_opportunity_explorer(state, repo_root=repo)

    row = result["opportunities"][0]
    assert row["status"] == "promotable_existing_owner_authority"
    assert row["evidence"] == "owner.example"
    assert result["review_refresh"]["approved_count"] == 1

    reviewed = json.loads((state / "authority_reviewed_grants.json").read_text())
    assert "api.owner.example" in reviewed["hosts"]


def test_hard_denial_never_retries_by_identity_or_transport_without_new_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    _repo_with_roots(repo, ["owner.example"])
    _candidate(state, "https://api.owner.example/v1")

    first = run_authority_opportunity_explorer(state, repo_root=repo)
    fingerprint = first["authority_evidence_fingerprint"]
    (state / "external_action_denials.ndjson").write_text(
        json.dumps(
            {
                "ts": 10,
                "target": "api.owner.example",
                "classification": "hard_deny",
                "authority_evidence_fingerprint": fingerprint,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    second = run_authority_opportunity_explorer(state, repo_root=repo)
    row = second["opportunities"][0]
    assert row["status"] == "hard_denial_wait_for_new_independent_evidence"
    assert row["authority_changed_since_denial"] is False
    assert row["alternate_identity_may_override_hard_denial"] is False
    assert second["global_rules"]["alternate_identity_bypass"] is False


def test_hard_denial_can_be_reconsidered_only_after_independent_authority_evidence_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    _repo_with_roots(repo, ["owner.example"])
    _candidate(state, "https://api.owner.example/v1")

    first = run_authority_opportunity_explorer(state, repo_root=repo)
    old_fingerprint = first["authority_evidence_fingerprint"]
    (state / "external_action_denials.ndjson").write_text(
        json.dumps(
            {
                "ts": 10,
                "target": "api.owner.example",
                "classification": "hard_deny",
                "authority_evidence_fingerprint": old_fingerprint,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Independent owner-side authority changed after the denial. The explorer may now
    # requeue the decision for authority review, but still does not override the denial
    # itself and does not rotate identity.
    _repo_with_roots(repo, ["owner.example", "second-owner.example"])
    second = run_authority_opportunity_explorer(state, repo_root=repo)
    row = second["opportunities"][0]
    assert row["authority_changed_since_denial"] is True
    assert row["status"] == "reconsider_hard_denial_with_new_independent_evidence"
    assert row["alternate_identity_may_override_hard_denial"] is False


def test_invalid_or_non_https_candidates_are_not_given_opportunity_rows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    repo.mkdir()
    state.mkdir()
    _repo_with_roots(repo, ["owner.example"])
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {"url": "http://owner.example/", "host": "owner.example", "decision": "candidate_only"},
                {"url": "not-a-url", "host": "owner.example", "decision": "candidate_only"},
            ]
        },
    )

    result = run_authority_opportunity_explorer(state, repo_root=repo)
    assert result["opportunity_count"] == 0
