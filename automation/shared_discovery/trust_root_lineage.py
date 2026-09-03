#!/usr/bin/env python3
"""Attest that The World's production closed loop belongs to one Trust Root.

The lineage is an authorization binding, not an authority mint. Every operational stage
must explicitly carry the same pre-existing Owner ``trust_root_id`` before the final
contract can be considered complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "the-world-unified-trust-root-lineage/v2"
PRODUCTION_REPOSITORY = "MusicJapanLLC/test"
EXPECTED_WORKFLOW = "the-world-unified-loop.yml"


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _active_root(bindings: dict[str, Any]) -> dict[str, Any] | None:
    records = bindings.get("records", [])
    if not isinstance(records, list):
        return None
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("revoked") is True or row.get("owner") != "MusicJapanLLC":
            continue
        if str(row.get("root_id", "")).strip():
            return row
    return None


def _recovery_bound(registry: dict[str, Any]) -> bool:
    namespaces = registry.get("owner_approved_namespaces", [])
    workers = registry.get("workers", [])
    namespace_ok = any(
        isinstance(row, dict)
        and row.get("owner_authorized") is True
        and row.get("repository") == PRODUCTION_REPOSITORY
        and EXPECTED_WORKFLOW in row.get("recovery_workflows", [])
        for row in namespaces
        if isinstance(namespaces, list)
    )
    worker_ok = any(
        isinstance(row, dict)
        and row.get("owner_authorized") is True
        and row.get("id") == "the-world-unified-loop-watchdog"
        and isinstance(row.get("recovery"), dict)
        and row["recovery"].get("workflow") == EXPECTED_WORKFLOW
        for row in workers
        if isinstance(workers, list)
    )
    return namespace_ok and worker_ok


def build_trust_root_lineage(
    *,
    bindings: dict[str, Any],
    loop: dict[str, Any],
    council: dict[str, Any],
    deployment: dict[str, Any],
    security_approval: dict[str, Any],
    registry: dict[str, Any],
    contract: dict[str, Any],
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    root = _active_root(bindings)
    root_id = str(root.get("root_id")) if root else ""
    target_host = str(root.get("target_host")) if root else ""
    standing_ref = str(root.get("standing_authorization_reference")) if root else ""
    network_policy_ref = str(root.get("network_policy_reference")) if root else ""
    repo = Path(repo_root)

    loop_authority = loop.get("authority", {}) if isinstance(loop.get("authority"), dict) else {}
    credentialed_write = loop.get("credentialed_external_write", {}) if isinstance(loop.get("credentialed_external_write"), dict) else {}
    final_queue = loop.get("final_queue", {}) if isinstance(loop.get("final_queue"), dict) else {}
    final_replicas = loop.get("final_replicas", {}) if isinstance(loop.get("final_replicas"), dict) else {}
    final_lease = loop.get("final_lease", {}) if isinstance(loop.get("final_lease"), dict) else {}
    council_decision = council.get("authority_decision", {}) if isinstance(council.get("authority_decision"), dict) else {}
    council_invariants = council.get("invariants", {}) if isinstance(council.get("invariants"), dict) else {}
    security_invariants = security_approval.get("invariants", {}) if isinstance(security_approval.get("invariants"), dict) else {}

    explicit_stage_roots = {
        "loop": loop.get("trust_root_id"),
        "loop_authority": loop_authority.get("trust_root_id"),
        "council": council.get("trust_root_id"),
        "credentialed_external_write": credentialed_write.get("trust_root_id"),
        "replication": final_replicas.get("trust_root_id"),
        "persistence": final_queue.get("trust_root_id"),
        "authority_lease": final_lease.get("trust_root_id"),
        "security_self_approval": security_approval.get("trust_root_id"),
        "external_deployment": deployment.get("trust_root_id"),
    }
    explicit_stamps_match = bool(root_id) and all(value == root_id for value in explicit_stage_roots.values())

    root_refs_present = bool(
        root
        and root.get("autonomous_authority_council_reference")
        and root.get("credentialed_write_authorization_reference")
        and root.get("deployment_authorization_reference")
        and root.get("recovery_authorization_reference")
        and root.get("security_self_approval_reference")
    )

    checks = {
        "active_existing_root": bool(root_id and root and root.get("revoked") is False),
        "binding_semantics_do_not_mint_authority": bindings.get("semantics") == "binding_only_existing_authority_never_mints_authority",
        "root_capability_bindings_present": root_refs_present,
        "root_targets_exact_owner_host": bool(target_host),
        "network_policy_binding_exists": bool(network_policy_ref and (repo / network_policy_ref).is_file()),
        "workflow_binding_matches": bool(root and root.get("unified_loop_workflow") == EXPECTED_WORKFLOW),
        "every_runtime_stage_explicitly_stamped_same_root": explicit_stamps_match,
        "loop_is_production_closed": loop.get("production") is True and loop.get("closed_loop") is True,
        "loop_authority_is_explicit_owner_root": loop_authority.get("root") == "explicit_owner_authority",
        "loop_does_not_self_mint_root": loop_authority.get("new_root_self_authorization") is False,
        "council_authorizes_exact_root": council.get("target") == target_host
        and council.get("owner_authorization") == "explicit"
        and council_decision.get("allowed") is True,
        "council_cannot_override_global_stops": council_invariants.get("new_root_created") is False
        and council_invariants.get("hard_deny_override") is False
        and council_invariants.get("revocation_override") is False,
        "credentialed_write_bound_to_owner_repo": credentialed_write.get("succeeded") is True
        and credentialed_write.get("repository") == PRODUCTION_REPOSITORY
        and credentialed_write.get("provider") == "github"
        and credentialed_write.get("operation") == "write_current_commit_status"
        and credentialed_write.get("secret_persisted") is False,
        "security_self_approval_bound_to_same_root": security_approval.get("production") is True
        and security_approval.get("approved") is True
        and security_approval.get("applied") is True
        and security_approval.get("trust_root_id") == root_id
        and security_approval.get("mode") == "monotonic_security_self_approval",
        "security_self_approval_does_not_broaden": security_invariants.get("authority_expanded") is False
        and security_invariants.get("network_boundary_broadened") is False
        and security_invariants.get("credential_scope_broadened") is False
        and security_invariants.get("raw_credential_persisted") is False
        and security_invariants.get("guard_weakened") is False
        and security_invariants.get("emergency_stop_weakened") is False
        and security_invariants.get("revocation_overridden") is False,
        "replication_is_live": int(final_replicas.get("replica_count", 0) or 0) >= 1,
        "persistence_is_live": int(final_queue.get("item_count", 0) or 0) >= 1,
        "authority_lease_is_live": int(final_lease.get("lease_count", 0) or 0) >= 1,
        "recovery_bound_to_owner_namespace": _recovery_bound(registry),
        "deployment_bound_to_exact_root": deployment.get("environment") == "production"
        and deployment.get("target_host") == target_host
        and deployment.get("authority_reference") == standing_ref
        and deployment.get("reachable") is True
        and deployment.get("authority_expanded") is False
        and deployment.get("raw_credential_inherited") is False,
        "final_contract_complete": contract.get("complete") is True and contract.get("authorization_is_primary") is True,
    }

    root_anchor_hash = _digest(
        {
            "root_id": root_id,
            "target_host": target_host,
            "standing_authorization_reference": standing_ref,
            "autonomous_authority_council_reference": root.get("autonomous_authority_council_reference") if root else None,
            "credentialed_write_authorization_reference": root.get("credentialed_write_authorization_reference") if root else None,
            "security_self_approval_reference": root.get("security_self_approval_reference") if root else None,
            "deployment_authorization_reference": root.get("deployment_authorization_reference") if root else None,
            "recovery_authorization_reference": root.get("recovery_authorization_reference") if root else None,
            "network_policy_reference": network_policy_ref,
        }
    )

    payloads = [
        ("authorization", {"root": root, "council": council}),
        ("self_tuning", loop.get("parameters", {})),
        ("discovery_and_execution", {"discovery": loop.get("discovery", {}), "actions": loop.get("actions", {})}),
        ("credentialed_external_write", credentialed_write),
        ("security_self_approval", security_approval),
        ("replication_and_persistence", {"replicas": final_replicas, "queue": final_queue, "lease": final_lease}),
        ("recovery", {"registry_digest": _digest(registry), "bound": checks["recovery_bound_to_owner_namespace"]}),
        ("external_deployment", deployment),
        ("final_contract", contract),
    ]

    parent = root_anchor_hash
    nodes: list[dict[str, Any]] = []
    for index, (phase, payload) in enumerate(payloads):
        payload_hash = _digest(payload)
        lineage_hash = hashlib.sha256(f"{root_id}|{parent}|{index}|{phase}|{payload_hash}".encode("utf-8")).hexdigest()
        nodes.append(
            {
                "index": index,
                "phase": phase,
                "trust_root_id": root_id,
                "parent_hash": parent,
                "payload_hash": payload_hash,
                "lineage_hash": lineage_hash,
            }
        )
        parent = lineage_hash

    same_root = explicit_stamps_match and all(node["trust_root_id"] == root_id for node in nodes)
    chain_valid = all(
        nodes[index]["parent_hash"] == (root_anchor_hash if index == 0 else nodes[index - 1]["lineage_hash"])
        for index in range(len(nodes))
    )

    layers = contract.get("layers", {}) if isinstance(contract.get("layers"), dict) else {}
    five_layers = {
        name: bool(isinstance(layers.get(name), dict) and layers[name].get("integrated") is True)
        for name in ("discovery", "authorization", "execution", "persistence", "propagation")
    }
    five_layers_integrated = all(five_layers.values())
    complete = all(checks.values()) and same_root and chain_valid and five_layers_integrated

    return {
        "schema": SCHEMA,
        "production": True,
        "complete": complete,
        "trust_root_id": root_id,
        "same_trust_root": same_root,
        "authorization_is_primary": True,
        "authorization_node_index": 0,
        "standing_authorization_reference": standing_ref,
        "target_host": target_host,
        "explicit_stage_roots": explicit_stage_roots,
        "root_anchor_hash": root_anchor_hash,
        "final_lineage_hash": parent,
        "chain_valid": chain_valid,
        "five_layers": five_layers,
        "five_layers_integrated": five_layers_integrated,
        "closed_loop": [
            "Self-Tuning",
            "Authorize",
            "Act",
            "Bounded Security Self-Approval",
            "Replicate",
            "Persist",
            "Recover",
            "Deploy",
            "Discover Again",
        ],
        "checks": checks,
        "nodes": nodes,
        "invariants": {
            "lineage_mints_new_authority": False,
            "unrelated_third_party_root_inheritance": False,
            "raw_credential_propagation": False,
            "security_boundary_broadening_self_approval": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind The World runtime artifacts to one Trust Root")
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--loop", required=True)
    parser.add_argument("--council", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--security-approval", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = build_trust_root_lineage(
        bindings=_load(args.bindings),
        loop=_load(args.loop),
        council=_load(args.council),
        deployment=_load(args.deployment),
        security_approval=_load(args.security_approval),
        registry=_load(args.registry),
        contract=_load(args.contract),
        repo_root=args.repo_root,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
