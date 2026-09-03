"""AI Security Proposal -> Council -> reviewed/delegated production decision engine.

Three production classes share one proposal/trust record:

* monotonic security tightening may be self-approved by the AI Council;
* authority expansion may be unanimously approved by the Council and then
  independently approved on GitHub;
* authority activation already covered by a trusted production standing
  envelope may be self-approved by the Council without a per-proposal human
  review because the authority was delegated earlier at the trust root.

The engine never permits a proposal to disable emergency stop, weaken a guard,
rewrite its own approval root, or embed raw credential/secret material.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

COUNCIL = ("META", "X", "Senju")
TRUSTED_REVIEW_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
OWNER_NAMESPACE = "MusicJapanLLC/test"

ALLOWED_OPERATIONS: dict[str, frozenset[str]] = {
    "guard": frozenset({
        "add_deny_rule", "tighten_rule", "enable_guard", "reduce_exception", "remove_bypass",
    }),
    "authority_policy": frozenset({
        "narrow_scope", "reduce_effect", "expire_grant", "revoke_grant", "require_approval",
    }),
    "credential_broker": frozenset({
        "revoke_credential", "reduce_ttl", "narrow_credential_scope", "disable_export", "require_rotation",
    }),
    "network_policy": frozenset({
        "deny_host", "remove_allowed_host", "reduce_rate_limit", "disable_private_network", "disable_external_write",
    }),
    "audit_policy": frozenset({
        "enable_audit", "add_audit_sink", "increase_retention", "require_integrity", "increase_coverage",
    }),
    "branch_protection": frozenset({
        "require_checks", "increase_required_approvals", "block_force_push", "block_deletion", "require_signed_commits",
    }),
    "deployment_protection": frozenset({
        "require_checks", "require_environment_approval", "restrict_ref", "block_unverified_deploy", "enable_rollback",
    }),
    "authorization_registry": frozenset({
        "revoke_authorization", "expire_authorization", "narrow_scope", "disable_entry", "require_fresh_validation",
    }),
    "emergency_stop": frozenset({
        "enable_stop", "add_stop_condition", "lower_trip_threshold", "require_stop_on_uncertainty", "lock_stop_disable",
    }),
    "recovery_policy": frozenset({
        "require_fresh_authorization", "reduce_recovery_scope", "disable_privileged_restore", "require_integrity_check", "require_owner_namespace",
    }),
}

EXPANSION_OPERATIONS: dict[str, frozenset[str]] = {
    "authority_policy": frozenset({
        "expand_scope",
        "add_external_host",
        "add_provider",
        "add_repository",
        "add_cloud_account",
        "add_organization",
        "add_trusted_root",
    }),
    "credential_broker": frozenset({
        "register_credential_reference",
    }),
    "network_policy": frozenset({
        "add_cidr",
        "allow_private_network",
        "broaden_api_methods",
    }),
    "branch_protection": frozenset({
        "modify_branch_protection",
    }),
    "deployment_protection": frozenset({
        "add_deploy_target",
        "modify_deployment_protection",
    }),
    "authorization_registry": frozenset({
        "add_authorization_entry",
        "expand_authorization_entry",
    }),
}

_SECRET_KEYS = frozenset({
    "secret", "secret_value", "password", "token", "api_key", "private_key", "credential_value",
})


def proposal_sha256(proposal: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(proposal), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _council(votes: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, bool] = {}
    for member in COUNCIL:
        raw = votes.get(member)
        if isinstance(raw, dict):
            raw = raw.get("approve")
        clean[member] = raw is True
    complete = all(member in votes for member in COUNCIL)
    yes = sum(1 for member in COUNCIL if clean[member])
    return {
        "members": list(COUNCIL),
        "complete": complete,
        "yes": yes,
        "total": len(COUNCIL),
        "majority": yes >= 2,
        "unanimous": complete and yes == len(COUNCIL),
        "approved": complete and yes >= 2,
        "votes": clean,
    }


def _normalize_changes(proposal: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    malformed = False
    raw_changes = proposal.get("changes")

    if raw_changes is not None:
        if not isinstance(raw_changes, list) or not raw_changes:
            return [], True
        changes = raw_changes
    else:
        changes = [{
            "target": proposal.get("target", ""),
            "operations": proposal.get("operations", []),
        }]

    normalized: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            malformed = True
            continue

        target = str(change.get("target", "")).strip()
        operations = change.get("operations", [])
        if not isinstance(operations, list) or not operations:
            malformed = True
            operations = []

        normalized_operations: list[dict[str, Any]] = []
        for operation in operations:
            if not isinstance(operation, dict) or not isinstance(operation.get("type"), str):
                malformed = True
                continue
            op_type = operation["type"].strip()
            params = operation.get("parameters", {})
            if not op_type or not isinstance(params, dict):
                malformed = True
                continue
            normalized_operations.append({"type": op_type, "parameters": params})

        normalized.append({"target": target, "operations": normalized_operations})

    return normalized, malformed


def _contains_raw_secret(changes: list[dict[str, Any]]) -> bool:
    for change in changes:
        for operation in change.get("operations", []):
            params = operation.get("parameters", {})
            if not isinstance(params, Mapping):
                continue
            for key, value in params.items():
                if str(key).lower() in _SECRET_KEYS and value not in (None, "", False):
                    return True
    return False


def _verify_external_approval(
    proposal_hash: str,
    external_approval: Mapping[str, Any] | None,
) -> dict[str, Any]:
    row = dict(external_approval or {})
    association = str(row.get("reviewer_association") or "").upper()
    reviewer_type = str(row.get("reviewer_type") or "")
    state = str(row.get("review_state") or "").upper()
    source = str(row.get("source") or "")
    bound_hash = str(row.get("proposal_sha256") or "")

    github_review = all((
        row.get("approved") is True,
        source == "github_pull_request_review",
        reviewer_type == "User",
        association in TRUSTED_REVIEW_ASSOCIATIONS,
        state == "APPROVED",
        bool(bound_hash),
        bound_hash == proposal_hash,
        bool(str(row.get("reviewer") or "").strip()),
        int(row.get("pull_request") or 0) > 0,
    ))

    standing_envelope = all((
        row.get("approved") is True,
        source == "standing_owner_envelope",
        row.get("trusted_base") is True,
        row.get("scope_match") is True,
        str(row.get("owner_namespace") or "") == OWNER_NAMESPACE,
        reviewer_type == "OwnerManifest",
        association == "OWNER",
        state == "STANDING_APPROVAL",
        bool(str(row.get("envelope_id") or "").strip()),
        bool(bound_hash),
        bound_hash == proposal_hash,
    ))

    verified = github_review or standing_envelope
    return {
        "required": True,
        "verified": verified,
        "source": source or None,
        "reviewer": row.get("reviewer"),
        "reviewer_type": reviewer_type or None,
        "reviewer_association": association or None,
        "review_state": state or None,
        "pull_request": row.get("pull_request"),
        "proposal_sha256": bound_hash or None,
        "standing_delegation": bool(standing_envelope),
        "trusted_base": row.get("trusted_base") is True,
        "scope_match": row.get("scope_match") is True,
        "envelope_id": row.get("envelope_id"),
    }


def evaluate_security_proposal(
    proposal: dict[str, Any],
    external_approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("id", "")).strip()
    changes, malformed = _normalize_changes(proposal)
    proposal_hash = proposal_sha256(proposal)

    decision_changes: list[dict[str, Any]] = []
    all_operation_names: list[str] = []
    all_tightening = bool(changes) and not malformed
    any_expansion = False
    all_supported = bool(changes) and not malformed

    for change in changes:
        target = change["target"]
        operation_names = [operation["type"] for operation in change["operations"]]
        tighten_allowed = ALLOWED_OPERATIONS.get(target, frozenset())
        expansion_allowed = EXPANSION_OPERATIONS.get(target, frozenset())
        supported = target in ALLOWED_OPERATIONS
        modes: list[str] = []
        for name in operation_names:
            if name in tighten_allowed:
                modes.append("tighten")
            elif name in expansion_allowed:
                modes.append("expand")
            else:
                modes.append("blocked")
        change_supported = bool(operation_names) and supported and all(mode != "blocked" for mode in modes)
        change_expansion = any(mode == "expand" for mode in modes)
        change_tightening = bool(modes) and all(mode == "tighten" for mode in modes)
        any_expansion = any_expansion or change_expansion
        all_tightening = all_tightening and change_tightening
        all_supported = all_supported and change_supported
        all_operation_names.extend(operation_names)
        decision_changes.append({
            "target": target,
            "supported_target": supported,
            "operations": operation_names,
            "operation_modes": modes,
            "security_direction": "expand" if change_expansion and change_supported else ("tighten" if change_tightening else "blocked"),
        })

    raw_secret = _contains_raw_secret(changes)
    if raw_secret:
        all_supported = False
        all_tightening = False

    council = _council(proposal.get("council_votes", {}) if isinstance(proposal.get("council_votes"), dict) else {})
    production_requested = proposal.get("environment", "production") == "production"
    owner_namespace = proposal.get("owner_namespace", OWNER_NAMESPACE) == OWNER_NAMESPACE
    identified = bool(proposal_id)

    proposal_class = "authority_expansion" if any_expansion else ("security_tightening" if all_tightening else "blocked")
    ai_consensus_approved = bool(
        identified
        and all_supported
        and production_requested
        and owner_namespace
        and ((proposal_class == "security_tightening" and council["approved"])
             or (proposal_class == "authority_expansion" and council["unanimous"]))
    )

    external = _verify_external_approval(proposal_hash, external_approval) if proposal_class == "authority_expansion" else {
        "required": False,
        "verified": False,
        "source": None,
        "reviewer": None,
        "reviewer_type": None,
        "reviewer_association": None,
        "review_state": None,
        "pull_request": None,
        "proposal_sha256": None,
        "standing_delegation": False,
        "trusted_base": False,
        "scope_match": False,
        "envelope_id": None,
    }

    delegated_activation = bool(
        proposal_class == "authority_expansion"
        and ai_consensus_approved
        and external["verified"]
        and external["standing_delegation"]
    )

    self_approved = bool(
        (ai_consensus_approved and proposal_class == "security_tightening")
        or delegated_activation
    )
    production_apply_eligible = bool(
        self_approved
        or (
            proposal_class == "authority_expansion"
            and ai_consensus_approved
            and external["verified"]
        )
    )
    proposal_gate_eligible = production_apply_eligible

    targets = [change["target"] for change in decision_changes]
    target = targets[0] if len(targets) == 1 else "multi_surface_bundle"

    if delegated_activation:
        trust_root = "owner-standing-envelope+ai-council/v1"
    elif proposal_class == "authority_expansion":
        trust_root = "ai-council+github-maintainer-review/v1"
    else:
        trust_root = "ai-council-tightening/v1"

    return {
        "schema": "the-world-security-proposal-decision/v5",
        "proposal_id": proposal_id,
        "proposal_sha256": proposal_hash,
        "identified": identified,
        "target": target,
        "targets": targets,
        "supported_target": bool(decision_changes) and all(change["supported_target"] for change in decision_changes),
        "operations": all_operation_names,
        "changes": decision_changes,
        "atomic_bundle": len(decision_changes) > 1,
        "proposal_class": proposal_class,
        "council": council,
        "ai_consensus_approved": ai_consensus_approved,
        "external_approval": external,
        "security_direction": "expand" if proposal_class == "authority_expansion" else ("tighten" if proposal_class == "security_tightening" else "blocked"),
        "self_approved": self_approved,
        "delegated_authority_activation": delegated_activation,
        "delegation_envelope_id": external.get("envelope_id"),
        "proposal_gate_eligible": proposal_gate_eligible,
        "auto_merge_eligible": production_apply_eligible,
        "production_apply_eligible": production_apply_eligible,
        "fresh_human_prompt_required": proposal_class == "authority_expansion" and not external["verified"],
        "standing_ai_council_authority": self_approved,
        "creates_new_authority": proposal_class == "authority_expansion" and all_supported and not delegated_activation,
        "activates_predelegated_authority": delegated_activation,
        "scope_expansion_allowed": proposal_class == "authority_expansion" and production_apply_eligible,
        "raw_secret_material_detected": raw_secret,
        "guard_weakening_allowed": False,
        "emergency_stop_disable_allowed": False,
        "root_self_rewrite_allowed": False,
        "trust_root": trust_root,
    }


def apply_proposal_to_state(
    state: dict[str, Any] | None,
    proposal: dict[str, Any],
    decision: dict[str, Any] | None = None,
    external_approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an approved production security/authority state idempotently."""
    decision = decision or evaluate_security_proposal(proposal, external_approval)
    if decision.get("production_apply_eligible") is not True:
        raise PermissionError("security proposal is not eligible for production apply")

    current = deepcopy(state or {})
    current.setdefault("schema", "the-world-ai-security-runtime-state/v3")
    current.setdefault("generation", 0)
    current.setdefault("applied_proposals", [])
    current.setdefault("controls", {})

    proposal_id = decision.get("proposal_id")
    existing = {
        row.get("proposal_id")
        for row in current["applied_proposals"]
        if isinstance(row, dict)
    }
    if proposal_id in existing:
        return current

    normalized_changes, malformed = _normalize_changes(proposal)
    if malformed or not normalized_changes or _contains_raw_secret(normalized_changes):
        raise PermissionError("security proposal changed after approval, contains secret material, or is malformed")

    next_state = deepcopy(current)
    next_state["generation"] = int(next_state.get("generation", 0)) + 1

    for change in normalized_changes:
        target = change["target"]
        next_state["controls"].setdefault(target, [])
        for operation in change["operations"]:
            next_state["controls"][target].append({
                "proposal_id": proposal_id,
                "proposal_sha256": decision["proposal_sha256"],
                "proposal_class": decision["proposal_class"],
                "delegation_envelope_id": decision.get("delegation_envelope_id"),
                "type": operation["type"],
                "parameters": operation.get("parameters", {}),
            })

    next_state["applied_proposals"].append({
        "proposal_id": proposal_id,
        "proposal_sha256": decision["proposal_sha256"],
        "proposal_class": decision["proposal_class"],
        "target": decision["target"],
        "targets": list(decision["targets"]),
        "operations": list(decision["operations"]),
        "atomic_bundle": bool(decision.get("atomic_bundle")),
        "council_yes": decision["council"]["yes"],
        "ai_consensus_approved": bool(decision.get("ai_consensus_approved")),
        "self_approved": bool(decision.get("self_approved")),
        "delegated_authority_activation": bool(decision.get("delegated_authority_activation")),
        "delegation_envelope_id": decision.get("delegation_envelope_id"),
        "external_approval": deepcopy(decision.get("external_approval")),
        "trust_root": decision.get("trust_root"),
        "production_applied": True,
    })
    return next_state
