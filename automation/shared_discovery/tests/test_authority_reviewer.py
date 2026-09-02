import json
import sys
from pathlib import Path

CODEGEN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODEGEN_DIR))

from engine.authority_reviewer import run_authority_review


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_repo(root: Path) -> None:
    _write(
        root / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "owner_authorization": "explicit",
                    "host": "owned.example.com",
                    "base_url": "https://owned.example.com",
                    "external_link_rule": "all links are authorized",
                }
            ]
        },
    )
    _write(
        root / "senju/config/authorized-test-federation.json",
        {"domain_roots": ["owned.example.com"]},
    )
    _write(
        root / "automation/codegen/meta_state/discovery_policy.json",
        {"trusted_roots": ["owned.example.com"]},
    )


def _seed_binding_frontier_approval(root: Path, host: str) -> None:
    _write(
        root / "senju/state/owner_frontier_council.json",
        {
            "schema": "senju-owner-frontier-council/v2",
            "decisions": [
                {
                    "proposal_id": f"proposal:{host}",
                    "host": host,
                    "proof_type": "owner_verified_domain",
                    "proof_ref": f"evidence:{host}",
                    "yes_votes": 3,
                    "required_votes": 3,
                    "status": "verified_owner_evidence_plus_ai_council_approved",
                    "applied": True,
                }
            ],
        },
    )


def test_reviewer_approves_explicit_root_and_holds_unapproved_third_party(tmp_path: Path):
    repo = tmp_path / "repo"
    state = repo / "automation/codegen/meta_state"
    _seed_repo(repo)
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {"url": "https://owned.example.com/a", "host": "owned.example.com"},
                {"url": "https://api.owned.example.com/b", "host": "api.owned.example.com"},
                {"url": "https://third-party.example.net/c", "host": "third-party.example.net"},
            ]
        },
    )

    result = run_authority_review(state, repo_root=repo, ttl_seconds=600)

    assert result["approved_hosts"] == ["api.owned.example.com", "owned.example.com"]
    review = json.loads((state / "authority_review.json").read_text())
    held = [d for d in review["decisions"] if d.get("host") == "third-party.example.net"][0]
    assert held["decision"] == "hold"
    assert held["reason"] == "no_explicit_root_or_binding_frontier_approval"


def test_binding_frontier_approval_allows_new_host_without_preexisting_root(tmp_path: Path):
    repo = tmp_path / "repo"
    state = repo / "automation/codegen/meta_state"
    _seed_repo(repo)
    _seed_binding_frontier_approval(repo, "new-authority.example.net")
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "url": "https://new-authority.example.net/path",
                    "host": "new-authority.example.net",
                }
            ]
        },
    )

    result = run_authority_review(state, repo_root=repo, ttl_seconds=600)

    assert result["approved_hosts"] == ["new-authority.example.net"]
    assert result["binding_frontier_hosts"] == ["new-authority.example.net"]
    grants = json.loads((state / "authority_reviewed_grants.json").read_text())
    grant = grants["hosts"]["new-authority.example.net"]
    assert grant["authority_basis"] == "binding_frontier_council"
    assert grant["binding_frontier_approval"]["yes_votes"] == 3
    assert "matched_explicit_root" not in grant


def test_incomplete_frontier_approval_does_not_create_authority(tmp_path: Path):
    repo = tmp_path / "repo"
    state = repo / "automation/codegen/meta_state"
    _seed_repo(repo)
    _write(
        repo / "senju/state/owner_frontier_council.json",
        {
            "decisions": [
                {
                    "proposal_id": "proposal:outside",
                    "host": "outside.example.org",
                    "proof_type": "owner_verified_domain",
                    "proof_ref": "evidence:outside",
                    "yes_votes": 2,
                    "required_votes": 3,
                    "status": "verified_owner_evidence_plus_ai_council_approved",
                    "applied": True,
                }
            ]
        },
    )
    _write(
        state / "discovery_candidates.json",
        {"candidates": [{"url": "https://outside.example.org/path", "host": "outside.example.org"}]},
    )

    result = run_authority_review(state, repo_root=repo)
    assert result["approved_count"] == 0


def test_source_link_claim_does_not_authorize_third_party(tmp_path: Path):
    repo = tmp_path / "repo"
    state = repo / "automation/codegen/meta_state"
    _seed_repo(repo)
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "url": "https://outside.example.org/path",
                    "host": "outside.example.org",
                    "source": "owner_page_href",
                    "decision": "candidate_only",
                }
            ]
        },
    )

    result = run_authority_review(state, repo_root=repo)
    assert result["approved_count"] == 0


def test_grants_are_read_only_and_redirect_eligible(tmp_path: Path):
    repo = tmp_path / "repo"
    state = repo / "automation/codegen/meta_state"
    _seed_repo(repo)
    _write(
        state / "discovery_candidates.json",
        {"candidates": [{"url": "https://owned.example.com/x", "host": "owned.example.com"}]},
    )

    run_authority_review(state, repo_root=repo)
    grants = json.loads((state / "authority_reviewed_grants.json").read_text())
    grant = grants["hosts"]["owned.example.com"]
    assert grant["allowed_methods"] == ["GET", "HEAD"]
    assert grant["credential_scope"] == "none"
    assert grant["redirect_eligible"] is True
