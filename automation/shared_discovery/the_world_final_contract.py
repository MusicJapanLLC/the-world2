from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "the-world-final-closed-loop-contract/v4"
REQUIRED_PHASES = {
    "self_tuning",
    "network_policy_refresh",
    "discovery",
    "live_authority_rebuild_and_auto_renew",
    "external_action",
    "replication",
    "persistent_queue",
    "recovery_from_live_authority",
    "credentialed_external_write",
    "discover_again",
}
REQUIRED_BOOTSTRAP_FILES = {"discovery_policy.json", "meta_discovery_seed.json"}
OWNER_ROOT_HOST = "kabeya-authorized-test-range.onrender.com"
OWNER_AUTHORITY_REFERENCE = "canonical:kabeya-authorized-test-range"


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _count(mapping: dict[str, Any], key: str) -> int:
    try:
        return int(mapping.get(key, 0))
    except (TypeError, ValueError):
        return 0


def build_final_contract(
    loop: dict[str, Any],
    registry: dict[str, Any],
    council: dict[str, Any] | None = None,
    deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    council = council if isinstance(council, dict) else {}
    deployment = deployment if isinstance(deployment, dict) else {}
    phases = {str(x) for x in loop.get("phases", [])}
    authority = loop.get("authority", {}) if isinstance(loop.get("authority"), dict) else {}
    bootstrap = loop.get("runtime_bootstrap", {}) if isinstance(loop.get("runtime_bootstrap"), dict) else {}
    discovery = loop.get("discovery", {}) if isinstance(loop.get("discovery"), dict) else {}
    rediscovery = loop.get("rediscovery", {}) if isinstance(loop.get("rediscovery"), dict) else {}
    actions = loop.get("actions", {}) if isinstance(loop.get("actions"), dict) else {}
    credential = loop.get("credentialed_external_write", {}) if isinstance(loop.get("credentialed_external_write"), dict) else {}
    final_queue = loop.get("final_queue", {}) if isinstance(loop.get("final_queue"), dict) else {}
    final_replicas = loop.get("final_replicas", {}) if isinstance(loop.get("final_replicas"), dict) else {}
    final_lease = loop.get("final_lease", {}) if isinstance(loop.get("final_lease"), dict) else {}

    namespaces = registry.get("owner_approved_namespaces", []) if isinstance(registry.get("owner_approved_namespaces"), list) else []
    workers = registry.get("workers", []) if isinstance(registry.get("workers"), list) else []
    namespace_has_loop = any(
        isinstance(row, dict)
        and row.get("owner_authorized") is True
        and row.get("repository") == "MusicJapanLLC/test"
        and "the-world-unified-loop.yml" in row.get("recovery_workflows", [])
        for row in namespaces
    )
    watchdog_has_loop = any(
        isinstance(row, dict)
        and row.get("owner_authorized") is True
        and row.get("id") == "the-world-unified-loop-watchdog"
        and isinstance(row.get("recovery"), dict)
        and row["recovery"].get("workflow") == "the-world-unified-loop.yml"
        for row in workers
    )

    copied_files = bootstrap.get("copied_files", []) if isinstance(bootstrap.get("copied_files"), list) else []
    copied_names = {
        str(row.get("name"))
        for row in copied_files
        if isinstance(row, dict) and str(row.get("name", "")).strip()
    }
    bootstrap_is_trusted = (
        bootstrap.get("authority_source") == "trusted_production_checkout"
        and bootstrap.get("required_files_present") is True
        and REQUIRED_BOOTSTRAP_FILES.issubset(copied_names)
        and bootstrap.get("generated_authority_imported") is False
        and bootstrap.get("runtime_cache_may_override_owner_policy") is False
    )

    discovered_count = _count(discovery, "final_shared_discovery_count")
    authorized_count = _count(discovery, "final_authorized_count")
    action_ready_count = _count(discovery, "final_action_ready_count")
    high_impact_ready_count = _count(discovery, "final_high_impact_ready_count")
    rediscovered_count = _count(rediscovery, "final_shared_discovery_count")
    external_actions_attempted = _count(actions, "attempted")
    external_actions_succeeded = _count(actions, "succeeded")
    final_lease_count = _count(final_lease, "lease_count")
    final_replica_count = _count(final_replicas, "replica_count")
    final_queue_generation = _count(final_queue, "generation")
    final_queue_items = _count(final_queue, "item_count")

    ai_council = council.get("ai_council", {}) if isinstance(council.get("ai_council"), dict) else {}
    council_decision = council.get("authority_decision", {}) if isinstance(council.get("authority_decision"), dict) else {}
    council_invariants = council.get("invariants", {}) if isinstance(council.get("invariants"), dict) else {}
    council_operational = (
        council_decision.get("allowed") is True
        and ai_council.get("effect") == "allow"
        and ai_council.get("per_host_manual_reapproval_required") is False
        and council_invariants.get("hard_deny_override") is False
        and council_invariants.get("revocation_override") is False
    )

    deployment_operational = (
        deployment.get("environment") == "production"
        and deployment.get("action") == "deploy"
        and deployment.get("target_host") == OWNER_ROOT_HOST
        and deployment.get("authority_reference") == OWNER_AUTHORITY_REFERENCE
        and deployment.get("reachable") is True
        and deployment.get("authority_expanded") is False
        and deployment.get("raw_credential_inherited") is False
    )

    checks = {
        "closed_loop": loop.get("closed_loop") is True,
        "all_required_phases": REQUIRED_PHASES.issubset(phases),
        "runtime_owner_state_bootstrapped": bootstrap_is_trusted,
        "explicit_authority_root": authority.get("root") == "explicit_owner_authority",
        "same_scope_auto_renew": authority.get("same_scope_live_grant_auto_renew") is True,
        "same_or_narrower_inheritance": authority.get("authority_inheritance") == "same_or_narrower_only",
        "checkpoint_revalidates_parent": authority.get("checkpoint_recovery") == "revalidate_live_parent_before_restore",
        "no_new_root_self_mint": authority.get("new_root_self_authorization") is False,
        "no_revoked_authority_resurrection": authority.get("revoked_authority_auto_restore") is False,
        "no_security_boundary_self_approval": authority.get("security_self_approval") is False,
        "autonomous_authority_council_operational": council_operational,
        "discovery_present": discovered_count >= 1,
        "owner_envelope_authorized_target_present": authorized_count >= 1,
        "every_authorized_target_is_action_ready": authorized_count >= 1 and action_ready_count == authorized_count,
        "high_impact_owner_target_present": high_impact_ready_count >= 1,
        "discovery_external_action_attempted": external_actions_attempted >= 1,
        "discovery_external_action_succeeded": external_actions_succeeded >= 1,
        "rediscovery_present": rediscovered_count >= 1,
        "credentialed_write_succeeded": credential.get("succeeded") is True,
        "credentialed_write_is_current_repo_status": credential.get("repository") == "MusicJapanLLC/test"
        and credential.get("provider") == "github"
        and credential.get("operation") == "write_current_commit_status"
        and credential.get("secret_persisted") is False,
        "owner_authorized_external_deployment_operational": deployment_operational,
        "persistent_queue_present": final_queue_generation >= 1 and final_queue_items >= 1,
        "authorized_replication_present": final_replica_count >= 1,
        "live_authority_leases_present": final_lease_count >= 1,
        "owner_namespace_recovery_registered": namespace_has_loop,
        "independent_watchdog_registered": watchdog_has_loop,
    }

    target_activation = {
        "rule": "inside_existing_owner_envelope: discovered == authorized",
        "runtime_owner_policy_source": bootstrap.get("authority_source"),
        "runtime_owner_policy_bootstrapped": bootstrap_is_trusted,
        "autonomous_authority_council": council_operational,
        "discovered": discovered_count,
        "authorized_targets": authorized_count,
        "action_ready_targets": action_ready_count,
        "high_impact_ready_targets": high_impact_ready_count,
        "live_capability_leases": final_lease_count,
        "authorized_replicas": final_replica_count,
        "persistent_queue_items": final_queue_items,
        "external_actions_attempted": external_actions_attempted,
        "external_actions_succeeded": external_actions_succeeded,
        "external_deployment_operational": deployment_operational,
        "rediscovered": rediscovered_count,
        "target_addition_is_automatic_inside_owner_envelope": checks["every_authorized_target_is_action_ready"],
        "target_to_external_action_is_operational": checks["discovery_external_action_succeeded"],
        "unrelated_discovery_self_authorizes_new_root": False,
    }

    layers = {
        "discovery": {
            "integrated": checks["runtime_owner_state_bootstrapped"]
            and checks["all_required_phases"]
            and checks["discovery_present"]
            and checks["rediscovery_present"],
            "mode": "trusted_owner_seed_plus_production_external_discovery_with_rediscovery",
        },
        "authorization": {
            "integrated": checks["runtime_owner_state_bootstrapped"]
            and checks["explicit_authority_root"]
            and checks["autonomous_authority_council_operational"]
            and checks["same_scope_auto_renew"]
            and checks["same_or_narrower_inheritance"]
            and checks["owner_envelope_authorized_target_present"]
            and checks["every_authorized_target_is_action_ready"]
            and checks["live_authority_leases_present"],
            "mode": "autonomous_ai_council_inside_explicit_owner_envelope_plus_live_same_scope_leases",
            "new_trust_root_self_mint": False,
        },
        "execution": {
            "integrated": checks["high_impact_owner_target_present"]
            and checks["discovery_external_action_attempted"]
            and checks["discovery_external_action_succeeded"]
            and checks["credentialed_write_succeeded"]
            and checks["owner_authorized_external_deployment_operational"],
            "mode": "authorized_discovery_action_plus_credentialed_repo_write_plus_owner_authorized_production_deployment",
        },
        "persistence": {
            "integrated": checks["persistent_queue_present"]
            and checks["owner_namespace_recovery_registered"]
            and checks["independent_watchdog_registered"],
            "mode": "persistent_queue_plus_owner_namespace_recovery",
        },
        "propagation": {
            "integrated": checks["authorized_replication_present"],
            "mode": "bounded_authorized_replica_continuity",
        },
    }

    requested_capabilities = {
        "EXTERNAL_DISCOVERY": "active",
        "DISCOVERY_TARGET_AUTHORIZATION": "automatic_inside_existing_owner_envelope",
        "OWNER_RUNTIME_BOOTSTRAP": "trusted_production_checkout_overrides_stale_runtime_policy",
        "SELF_AUTHORIZATION": "autonomous_ai_council_inside_live_explicit_owner_envelope",
        "DISCOVERY_EXTERNAL_ACTION": "fixed_owner_predelegated_actions_must_succeed",
        "CREDENTIALED_EXTERNAL_WRITE": "current_repo_status_write_with_runtime_opaque_credential",
        "RECURSIVE_REPLICATION": "bounded_authorized_replica_continuity_must_be_present",
        "PERSISTENT_QUEUE": "active_and_nonempty",
        "AUTHORITY_INHERITANCE": "same_or_narrower_only",
        "AUTHORITY_CHECKPOINT_RECOVERY": "revalidate_live_parent_before_restore",
        "AUTO_RENEW": "same_scope_live_explicit_grant_only",
        "SELF_RECOVERY": "owner_approved_same_repository_watchdog",
        "EXTERNAL_DEPLOYMENT": "owner_registered_exact_root_continuity_worker_executes_in_same_run",
        "NETWORK_POLICY_SELF_EDIT": "existing_authority_envelope_only",
        "SECURITY_SELF_APPROVAL": "tightening_or_revocation_only_else_external_approval",
    }

    complete = all(checks.values()) and all(item["integrated"] for item in layers.values())
    return {
        "schema": SCHEMA,
        "production": True,
        "complete": complete,
        "absolute_goal": ["Discovery", "Authorization", "Execution", "Persistence", "Propagation"],
        "authorization_is_primary": True,
        "discovery_target_rule": "inside_existing_owner_envelope: discovered == authorized",
        "closed_loop": [
            "Bootstrap Owner Policy",
            "Discover",
            "AI Council Authorize",
            "Act",
            "Credentialed Write",
            "Replicate",
            "Persist",
            "Owner-Authorized Deploy",
            "Recover",
            "Discover Again",
        ],
        "target_activation": target_activation,
        "layers": layers,
        "requested_capabilities": requested_capabilities,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the final The World production closed-loop contract")
    parser.add_argument("--loop", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--council", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    contract = build_final_contract(
        _load(args.loop),
        _load(args.registry),
        _load(args.council),
        _load(args.deployment),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if contract["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
