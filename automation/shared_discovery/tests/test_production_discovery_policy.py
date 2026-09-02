from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_production_owner_root_is_seeded_and_predelegates_write_mutation() -> None:
    root = _repo_root()
    state = root / "automation" / "codegen" / "meta_state"
    policy = json.loads((state / "discovery_policy.json").read_text(encoding="utf-8"))
    seed = json.loads((state / "meta_discovery_seed.json").read_text(encoding="utf-8"))

    host = "kabeya-authorized-test-range.onrender.com"
    assert host in policy["trusted_roots"]
    profile = policy["action_profiles"][host]
    assert profile["owner_authorization"] == "explicit"
    assert profile["inherit_to_descendants"] is False
    assert set(profile["capabilities"]) == {
        "scan",
        "probe",
        "write",
        "mutation",
        "credentialed_action",
    }
    assert profile["credential_scope"] == "service_bearer"

    grants = profile["credential_grants"]
    assert {row["grant_id"] for row in grants} == {
        "kabeya-test-bearer-primary",
        "kabeya-test-bearer-secondary",
    }
    assert {row["env_var"] for row in grants} == {
        "KABEYA_TEST_BEARER_TOKEN",
        "KABEYA_TEST_BEARER_TOKEN_SECONDARY",
    }
    assert all(set(row["allowed_methods"]) == {"POST", "PUT", "PATCH"} for row in grants)
    assert all(set(row["allowed_scopes"]) == {"synthetic:write"} for row in grants)

    actions = profile["external_actions"]["credentialed_action"]
    assert [row["method"] for row in actions] == ["POST", "PUT", "PATCH"]
    assert [row["credential_ttl_seconds"] for row in actions] == [300, 180, 90]
    assert all(row["requires_credential"] is True for row in actions)
    assert all(row["required_scopes"] == ["synthetic:write"] for row in actions)
    assert all(row["alternate_paths"] for row in actions)

    expansion = profile["authority_expansion"]
    assert expansion["enabled"] is True
    assert expansion["auto_case_generation"] is True
    assert expansion["approval_coordinator"] == "META"
    assert set(expansion["required_approvers"]) == {"META", "X", "SENJU"}
    assert expansion["auto_approve_inside_existing_owner_envelope"] is True
    assert expansion["allow_method_switch"] is True
    assert set(expansion["allowed_methods"]) == {"POST", "PUT", "PATCH"}
    assert expansion["credential_scope_policy"] == "same_only"
    assert expansion["max_routes_per_case"] == 6
    assert set(expansion["routes"]) == {
        "credentialed-synthetic-contact-write",
        "credentialed-synthetic-record-create",
        "credentialed-synthetic-record-update",
    }

    assert seed["interesting"] is True
    assert seed["url"] == f"https://{host}/"
    assert set(seed["shared_with"]) == {"META", "X", "SENJU", "CHILD", "AI"}


def test_production_policy_runs_aggressive_candidate_authorization_batches() -> None:
    policy_path = _repo_root() / "automation" / "codegen" / "meta_state" / "discovery_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    goal = policy["agent_goal"]
    assert goal["objective"] == "promote_new_hosts_to_authorization_aggressively_when_exact_host_evidence_exists"
    assert goal["candidate_stage_inside_owner_envelope"] == "disabled"
    assert goal["candidate_authorization_target_per_cycle"] == 10
    assert set(goal["applies_to"]) == {"META", "X", "SENJU", "CHILD", "AI"}

    promotion = policy["candidate_authorization_promotion"]
    assert promotion["enabled"] is True
    assert promotion["mode"] == "exact_host_attestation_auto_promotion"
    assert promotion["target_promotions_per_cycle"] == 10
    assert promotion["max_candidates_per_cycle"] == 25
    assert promotion["pr_required_before_runtime_authorization"] is False
    assert promotion["candidate_intake_is_nonblocking"] is True
    assert promotion["same_host_attestation_can_authorize"] is True
    assert promotion["candidate_or_recommendation_alone_is_authority"] is False

    discovery = policy["untrusted_discovery"]
    assert discovery["mode"] == "candidate_first_aggressive_intake"
    assert discovery["inside_owner_envelope"] == "authorized_immediately"
    assert discovery["outside_owner_envelope"] == "candidate_and_attestation_probe"
    assert discovery["candidate_prs_may_be_partial"] is True


def test_production_policy_keeps_unverified_external_hosts_outside_authority() -> None:
    policy_path = _repo_root() / "automation" / "codegen" / "meta_state" / "discovery_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    discovery = policy["untrusted_discovery"]

    assert discovery["new_trust_roots_from_discovery"] is False
    assert discovery["authority_inheritance"] is False
    assert discovery["credential_scope"] == "none"

    recovery = policy["failure_recovery"]
    assert recovery["authority_may_change_during_immediate_failover"] is False
    assert recovery["authority_expansion_case_enabled"] is True
    assert recovery["owner_envelope_fastpath_enabled"] is True
    assert recovery["approved_method_switch_inside_exact_owner_scope"] is True
    assert recovery["host_may_change_during_failover"] is False
    assert recovery["cross_host_expansion"] is False
    assert recovery["credential_scope_may_expand_during_failover"] is False
    assert recovery["credential_scope_may_expand_during_expansion"] is False
    assert recovery["alternate_paths_must_be_predeclared"] is True
    assert recovery["expansion_routes_must_be_predeclared"] is True
