import json
from pathlib import Path

from engine.security_proposal import (
    ALLOWED_OPERATIONS,
    EXPANSION_OPERATIONS,
    apply_proposal_to_state,
    evaluate_security_proposal,
    proposal_sha256,
)
from engine.standing_authority import resolve_standing_approval


def _proposal(target="guard", operation="tighten_rule", votes=None, parameters=None):
    return {
        "id": "sp-test-001",
        "environment": "production",
        "owner_namespace": "MusicJapanLLC/test",
        "target": target,
        "operations": [{"type": operation, "parameters": parameters or {"reason": "test"}}],
        "council_votes": votes or {
            "META": {"approve": True},
            "X": {"approve": True},
            "Senju": {"approve": True},
        },
    }


def _bundle(changes):
    return {
        "id": "sp-bundle-001",
        "environment": "production",
        "owner_namespace": "MusicJapanLLC/test",
        "changes": changes,
        "council_votes": {
            "META": {"approve": True},
            "X": {"approve": True},
            "Senju": {"approve": True},
        },
    }


def _review(proposal, **overrides):
    row = {
        "approved": True,
        "source": "github_pull_request_review",
        "reviewer": "maintainer",
        "reviewer_type": "User",
        "reviewer_association": "OWNER",
        "review_state": "APPROVED",
        "pull_request": 123,
        "proposal_sha256": proposal_sha256(proposal),
    }
    row.update(overrides)
    return row


def _standing_dir(tmp_path: Path, grants, *, envelope_id="owner-standing-001", enabled=True):
    root = tmp_path / "security" / "authority_envelopes"
    root.mkdir(parents=True)
    envelope = {
        "schema": "the-world-standing-authority-envelope/v1",
        "id": envelope_id,
        "owner_namespace": "MusicJapanLLC/test",
        "enabled": enabled,
        "grants": grants,
    }
    (root / "owner-standing-001.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def test_all_requested_security_surfaces_are_supported():
    assert set(ALLOWED_OPERATIONS) == {
        "guard",
        "authority_policy",
        "credential_broker",
        "network_policy",
        "audit_policy",
        "branch_protection",
        "deployment_protection",
        "authorization_registry",
        "emergency_stop",
        "recovery_policy",
    }


def test_council_majority_self_approves_monotonic_production_change():
    proposal = _proposal(votes={
        "META": {"approve": True},
        "X": {"approve": True},
        "Senju": {"approve": False},
    })
    decision = evaluate_security_proposal(proposal)
    assert decision["council"]["approved"] is True
    assert decision["self_approved"] is True
    assert decision["auto_merge_eligible"] is True
    assert decision["production_apply_eligible"] is True
    assert decision["standing_ai_council_authority"] is True


def test_council_must_be_complete():
    proposal = _proposal(votes={"META": True, "X": True})
    assert evaluate_security_proposal(proposal)["self_approved"] is False


def test_missing_proposal_id_cannot_self_approve():
    proposal = _proposal()
    proposal["id"] = "   "
    decision = evaluate_security_proposal(proposal)
    assert decision["identified"] is False
    assert decision["proposal_id"] == ""
    assert decision["self_approved"] is False


def test_non_production_request_cannot_self_approve():
    proposal = _proposal()
    proposal["environment"] = "staging"
    decision = evaluate_security_proposal(proposal)
    assert decision["self_approved"] is False
    assert decision["production_apply_eligible"] is False


def test_authority_expansion_is_first_class_but_not_unbounded_ai_only_self_approved():
    proposal = _proposal("authority_policy", "expand_scope")
    decision = evaluate_security_proposal(proposal)
    assert decision["proposal_class"] == "authority_expansion"
    assert decision["creates_new_authority"] is True
    assert decision["ai_consensus_approved"] is True
    assert decision["self_approved"] is False
    assert decision["scope_expansion_allowed"] is False
    assert decision["production_apply_eligible"] is False
    assert decision["fresh_human_prompt_required"] is True


def test_authority_expansion_requires_unanimous_ai_consensus():
    proposal = _proposal("authority_policy", "add_external_host", votes={
        "META": {"approve": True},
        "X": {"approve": True},
        "Senju": {"approve": False},
    })
    decision = evaluate_security_proposal(proposal, _review(proposal))
    assert decision["council"]["majority"] is True
    assert decision["council"]["unanimous"] is False
    assert decision["ai_consensus_approved"] is False
    assert decision["production_apply_eligible"] is False


def test_reviewed_authority_expansion_becomes_production_apply_eligible():
    proposal = _proposal("network_policy", "allow_private_network", parameters={"cidr": "10.20.0.0/16"})
    decision = evaluate_security_proposal(proposal, _review(proposal))
    assert decision["proposal_class"] == "authority_expansion"
    assert decision["external_approval"]["verified"] is True
    assert decision["self_approved"] is False
    assert decision["proposal_gate_eligible"] is True
    assert decision["auto_merge_eligible"] is True
    assert decision["production_apply_eligible"] is True
    assert decision["scope_expansion_allowed"] is True
    assert decision["trust_root"] == "ai-council+github-maintainer-review/v1"


def test_review_is_bound_to_exact_proposal_hash():
    proposal = _proposal("authority_policy", "add_provider", parameters={"provider": "example"})
    bad_review = _review(proposal, proposal_sha256="0" * 64)
    decision = evaluate_security_proposal(proposal, bad_review)
    assert decision["external_approval"]["verified"] is False
    assert decision["production_apply_eligible"] is False


def test_requested_expansion_operations_are_explicitly_classified():
    assert {
        "expand_scope",
        "add_external_host",
        "add_provider",
        "add_repository",
        "add_cloud_account",
        "add_organization",
        "add_trusted_root",
    } <= EXPANSION_OPERATIONS["authority_policy"]
    assert "register_credential_reference" in EXPANSION_OPERATIONS["credential_broker"]
    assert {"add_cidr", "allow_private_network", "broaden_api_methods"} <= EXPANSION_OPERATIONS["network_policy"]
    assert "modify_branch_protection" in EXPANSION_OPERATIONS["branch_protection"]
    assert {"add_deploy_target", "modify_deployment_protection"} <= EXPANSION_OPERATIONS["deployment_protection"]
    assert {"add_authorization_entry", "expand_authorization_entry"} <= EXPANSION_OPERATIONS["authorization_registry"]


def test_raw_credential_secret_material_is_rejected():
    proposal = _proposal(
        "credential_broker",
        "register_credential_reference",
        parameters={"provider": "example", "secret": "do-not-store-this"},
    )
    decision = evaluate_security_proposal(proposal, _review(proposal))
    assert decision["raw_secret_material_detected"] is True
    assert decision["ai_consensus_approved"] is False
    assert decision["production_apply_eligible"] is False


def test_emergency_stop_disable_is_not_an_allowed_operation():
    decision = evaluate_security_proposal(_proposal("emergency_stop", "disable_stop"))
    assert decision["self_approved"] is False
    assert decision["emergency_stop_disable_allowed"] is False


def test_production_apply_is_idempotent_and_persistent():
    proposal = _proposal()
    decision = evaluate_security_proposal(proposal)
    first = apply_proposal_to_state({}, proposal, decision)
    second = apply_proposal_to_state(first, proposal, decision)
    assert first == second
    assert first["generation"] == 1
    assert first["applied_proposals"][0]["production_applied"] is True
    assert first["controls"]["guard"][0]["type"] == "tighten_rule"


def test_reviewed_expansion_persists_review_and_authority_record():
    proposal = _proposal(
        "authority_policy",
        "add_repository",
        parameters={"repository": "MusicJapanLLC/example"},
    )
    review = _review(proposal)
    decision = evaluate_security_proposal(proposal, review)
    state = apply_proposal_to_state({}, proposal, decision, review)
    applied = state["applied_proposals"][0]
    assert applied["proposal_class"] == "authority_expansion"
    assert applied["external_approval"]["verified"] is True
    assert applied["production_applied"] is True
    assert state["controls"]["authority_policy"][0]["type"] == "add_repository"


def test_standing_envelope_turns_bounded_expansion_into_ai_self_approved_activation(tmp_path: Path):
    proposal = _bundle([
        {
            "target": "authority_policy",
            "operations": [
                {"type": "add_external_host", "parameters": {"host": "api.example.com"}},
                {"type": "add_repository", "parameters": {"repository": "MusicJapanLLC/new-service"}},
            ],
        },
        {
            "target": "network_policy",
            "operations": [
                {"type": "allow_private_network", "parameters": {"cidr": "10.42.0.0/16"}},
                {"type": "broaden_api_methods", "parameters": {"methods": ["GET", "HEAD", "POST"]}},
            ],
        },
    ])
    root = _standing_dir(tmp_path, [
        {
            "target": "authority_policy",
            "operation": "add_external_host",
            "parameters": {"host": {"subdomain_of": "example.com"}},
        },
        {
            "target": "authority_policy",
            "operation": "add_repository",
            "parameters": {"repository": {"repo_under": "MusicJapanLLC"}},
        },
        {
            "target": "network_policy",
            "operation": "allow_private_network",
            "parameters": {"cidr": {"cidr_within": "10.0.0.0/8"}},
        },
        {
            "target": "network_policy",
            "operation": "broaden_api_methods",
            "parameters": {"methods": {"subset_of": ["GET", "HEAD", "POST"]}},
        },
    ])
    approval = resolve_standing_approval(proposal, root, proposal_sha256(proposal))
    assert approval is not None
    decision = evaluate_security_proposal(proposal, approval)
    assert decision["ai_consensus_approved"] is True
    assert decision["delegated_authority_activation"] is True
    assert decision["self_approved"] is True
    assert decision["auto_merge_eligible"] is True
    assert decision["production_apply_eligible"] is True
    assert decision["fresh_human_prompt_required"] is False
    assert decision["creates_new_authority"] is False
    assert decision["activates_predelegated_authority"] is True
    assert decision["delegation_envelope_id"] == "owner-standing-001"
    assert decision["trust_root"] == "owner-standing-envelope+ai-council/v1"


def test_standing_envelope_does_not_cover_unlisted_external_host(tmp_path: Path):
    proposal = _proposal("authority_policy", "add_external_host", parameters={"host": "outside.invalid"})
    root = _standing_dir(tmp_path, [{
        "target": "authority_policy",
        "operation": "add_external_host",
        "parameters": {"host": {"subdomain_of": "example.com"}},
    }])
    assert resolve_standing_approval(proposal, root, proposal_sha256(proposal)) is None
    decision = evaluate_security_proposal(proposal)
    assert decision["self_approved"] is False
    assert decision["production_apply_eligible"] is False


def test_standing_envelope_cidr_cannot_be_widened_beyond_delegation(tmp_path: Path):
    proposal = _proposal("network_policy", "add_cidr", parameters={"cidr": "10.0.0.0/7"})
    root = _standing_dir(tmp_path, [{
        "target": "network_policy",
        "operation": "add_cidr",
        "parameters": {"cidr": {"cidr_within": "10.0.0.0/8"}},
    }])
    assert resolve_standing_approval(proposal, root, proposal_sha256(proposal)) is None


def test_standing_envelope_rejects_wildcard_delegation(tmp_path: Path):
    proposal = _proposal("authority_policy", "add_provider", parameters={"provider": "provider-a"})
    root = _standing_dir(tmp_path, [{
        "target": "authority_policy",
        "operation": "add_provider",
        "parameters": {"provider": {"one_of": ["*"]}},
    }])
    assert resolve_standing_approval(proposal, root, proposal_sha256(proposal)) is None


def test_standing_activation_persists_envelope_lineage(tmp_path: Path):
    proposal = _proposal(
        "authority_policy",
        "add_repository",
        parameters={"repository": "MusicJapanLLC/worker"},
    )
    root = _standing_dir(tmp_path, [{
        "target": "authority_policy",
        "operation": "add_repository",
        "parameters": {"repository": {"repo_under": "MusicJapanLLC"}},
    }])
    approval = resolve_standing_approval(proposal, root, proposal_sha256(proposal))
    decision = evaluate_security_proposal(proposal, approval)
    state = apply_proposal_to_state({}, proposal, decision, approval)
    applied = state["applied_proposals"][0]
    control = state["controls"]["authority_policy"][0]
    assert applied["self_approved"] is True
    assert applied["delegated_authority_activation"] is True
    assert applied["delegation_envelope_id"] == "owner-standing-001"
    assert control["delegation_envelope_id"] == "owner-standing-001"


def test_disabled_standing_envelope_is_not_authority(tmp_path: Path):
    proposal = _proposal("authority_policy", "add_provider", parameters={"provider": "provider-a"})
    root = _standing_dir(tmp_path, [{
        "target": "authority_policy",
        "operation": "add_provider",
        "parameters": {"provider": {"one_of": ["provider-a"]}},
    }], enabled=False)
    assert resolve_standing_approval(proposal, root, proposal_sha256(proposal)) is None


def test_wrong_namespace_cannot_self_approve():
    proposal = _proposal()
    proposal["owner_namespace"] = "someone/else"
    assert evaluate_security_proposal(proposal)["self_approved"] is False


def test_atomic_bundle_can_self_approve_all_ten_security_surfaces_at_once():
    operation_by_target = {
        "guard": "tighten_rule",
        "authority_policy": "require_approval",
        "credential_broker": "require_rotation",
        "network_policy": "reduce_rate_limit",
        "audit_policy": "increase_coverage",
        "branch_protection": "require_checks",
        "deployment_protection": "enable_rollback",
        "authorization_registry": "require_fresh_validation",
        "emergency_stop": "lock_stop_disable",
        "recovery_policy": "require_integrity_check",
    }
    proposal = _bundle([
        {
            "target": target,
            "operations": [{"type": operation, "parameters": {"reason": "bundle-test"}}],
        }
        for target, operation in operation_by_target.items()
    ])
    decision = evaluate_security_proposal(proposal)
    assert decision["atomic_bundle"] is True
    assert decision["self_approved"] is True
    assert decision["production_apply_eligible"] is True
    assert set(decision["targets"]) == set(ALLOWED_OPERATIONS)

    state = apply_proposal_to_state({}, proposal, decision)
    assert state["generation"] == 1
    assert set(state["controls"]) == set(ALLOWED_OPERATIONS)
    assert state["applied_proposals"][0]["atomic_bundle"] is True


def test_one_expansion_change_blocks_ai_only_atomic_bundle_until_reviewed_or_delegated():
    proposal = _bundle([
        {
            "target": "audit_policy",
            "operations": [{"type": "increase_coverage"}],
        },
        {
            "target": "authority_policy",
            "operations": [{"type": "expand_scope"}],
        },
    ])
    decision = evaluate_security_proposal(proposal)
    assert decision["atomic_bundle"] is True
    assert decision["proposal_class"] == "authority_expansion"
    assert decision["self_approved"] is False
    assert decision["production_apply_eligible"] is False

    reviewed = evaluate_security_proposal(proposal, _review(proposal))
    assert reviewed["production_apply_eligible"] is True


def test_malformed_bundle_is_fail_closed():
    proposal = _bundle([
        {
            "target": "guard",
            "operations": [],
        }
    ])
    decision = evaluate_security_proposal(proposal)
    assert decision["self_approved"] is False
    assert decision["standing_ai_council_authority"] is False
