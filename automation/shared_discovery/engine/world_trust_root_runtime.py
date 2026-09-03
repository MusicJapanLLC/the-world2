"""WORLD production trust-root coordinator.

This module does not replace the existing discovery, authorization, execution,
replication, persistence, recovery, network-policy, credential, or security engines.
It consumes their durable evidence and joins it under one lineage/checkpoint so the
existing systems can cooperate without duplicating implementation.

The coordinator deliberately does not mint a new Internet trust root, invent a
credential, widen an Authority lease, or convert a Guard denial into permission.
High-impact execution is represented as an intent only when the current owner-derived
capability lease already contains that capability. A concrete write/mutation executor
must still be independently registered for that exact capability/profile.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

CHECKPOINT_SCHEMA = "world-trust-root-runtime/v1"
INTENT_SCHEMA = "world-trust-root-execution-intents/v1"
HANDOFF_SCHEMA = "world-trust-root-handoffs/v1"
CONFIG_SCHEMA = "world-trust-root-config/v1"
LEASE_SCHEMA = "meta-discovery-capability-leases/v1"

DEFAULT_TRUST_ROOT_ID = "world:existing-owner-authority"
DEFAULT_ACTORS = ("META", "X", "SENJU", "CHILD", "AI")
HIGH_IMPACT_CAPABILITIES = frozenset({"write", "mutation", "credentialed_action"})
READ_CAPABILITIES = frozenset({"scan", "probe"})

DEFAULT_STALE_AFTER = {
    "shared_discovery": 4500,
    "network_policy": 1200,
    "external_recovery": 9000,
    "production_continuity": 4500,
}

WORKFLOW_HANDOFFS = {
    "shared_discovery": "shared-discovery-authority-cycle.yml",
    "network_policy": "meta-network-policy-expansion.yml",
    "external_recovery": "senju-external-recovery-cycle.yml",
    "production_continuity": "meta-x-production-continuity.yml",
}


class WorldTrustRootError(RuntimeError):
    """Raised when the unified runtime evidence is malformed."""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _first(root: Path, *names: str) -> Path | None:
    if not root.exists():
        return None
    for name in names:
        direct = root / name
        if direct.is_file():
            return direct
    for name in names:
        matches = sorted(root.rglob(name), key=lambda item: item.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


def _age_seconds(path: Path | None, *, now: int) -> int | None:
    if path is None or not path.exists():
        return None
    return max(0, now - int(path.stat().st_mtime))


def _hash_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "schema": CONFIG_SCHEMA,
            "environment": "production",
            "trust_root_id": DEFAULT_TRUST_ROOT_ID,
            "actors": list(DEFAULT_ACTORS),
            "stale_after_seconds": dict(DEFAULT_STALE_AFTER),
        }
    payload = _read_json(path, {})
    if not isinstance(payload, Mapping) or payload.get("schema") != CONFIG_SCHEMA:
        raise WorldTrustRootError("invalid WORLD trust-root config")
    if payload.get("environment") != "production":
        raise WorldTrustRootError("WORLD trust-root config must declare environment=production")
    return dict(payload)


def _active_leases(shared_state_dir: Path, *, now: int) -> list[dict[str, Any]]:
    path = shared_state_dir / "discovery_capability_leases.json"
    payload = _read_json(path, {})
    if not isinstance(payload, Mapping) or payload.get("schema") != LEASE_SCHEMA:
        return []
    leases: list[dict[str, Any]] = []
    for raw in payload.get("leases", []):
        if not isinstance(raw, Mapping):
            continue
        try:
            expires_at = int(raw.get("expires_at", 0))
        except (TypeError, ValueError):
            continue
        if str(raw.get("status", "active")) != "active" or expires_at <= now:
            continue
        target = str(raw.get("target") or "").strip().lower().rstrip(".")
        reference = str(raw.get("authorization_reference") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not target or not reference or not url:
            continue
        capabilities = sorted(
            {
                str(item).strip().lower()
                for item in raw.get("capabilities", [])
                if str(item).strip().lower() in READ_CAPABILITIES | HIGH_IMPACT_CAPABILITIES
            }
        )
        if not capabilities:
            continue
        scope = str(raw.get("credential_scope", "none")).strip() or "none"
        if "credentialed_action" in capabilities and scope == "none":
            capabilities = [item for item in capabilities if item != "credentialed_action"]
        if not capabilities:
            continue
        profile = raw.get("capability_authorization_profile")
        if any(item in HIGH_IMPACT_CAPABILITIES for item in capabilities):
            if not isinstance(profile, str) or not profile.strip():
                capabilities = [item for item in capabilities if item in READ_CAPABILITIES]
                scope = "none"
        if not capabilities:
            continue
        leases.append(
            {
                "lease_id": str(raw.get("lease_id") or ""),
                "target": target,
                "url": url,
                "authorization_reference": reference,
                "authorization_basis": raw.get("authorization_basis"),
                "capability_authorization_profile": profile if isinstance(profile, str) else None,
                "capability_inherited_from_owner_root": bool(raw.get("capability_inherited_from_owner_root", False)),
                "capabilities": capabilities,
                "credential_scope": scope,
                "shared_with": sorted({str(x).strip().upper() for x in raw.get("shared_with", []) if str(x).strip()}),
                "issued_at": int(raw.get("issued_at", 0) or 0),
                "expires_at": expires_at,
            }
        )
    leases.sort(key=lambda item: (item["target"], item["lease_id"]))
    return leases


def _execution_intents(
    leases: Sequence[Mapping[str, Any]],
    *,
    trust_root_id: str,
    now: int,
) -> list[dict[str, Any]]:
    intents: list[dict[str, Any]] = []
    for lease in leases:
        caps = tuple(str(x) for x in lease.get("capabilities", []))
        for capability in caps:
            high_impact = capability in HIGH_IMPACT_CAPABILITIES
            credential_scope = str(lease.get("credential_scope", "none"))
            if capability == "credentialed_action" and credential_scope == "none":
                continue
            mode = "existing_read_executor"
            registered_executor_required = False
            if high_impact:
                mode = "registered_high_impact_executor_required"
                registered_executor_required = True
            intents.append(
                {
                    "schema": "world-trust-root-execution-intent/v1",
                    "intent_id": _hash_id(
                        trust_root_id,
                        lease.get("lease_id"),
                        lease.get("target"),
                        capability,
                    ),
                    "created_at": now,
                    "trust_root_id": trust_root_id,
                    "target": lease.get("target"),
                    "url": lease.get("url"),
                    "capability": capability,
                    "high_impact": high_impact,
                    "credential_scope": credential_scope,
                    "authorization_reference": lease.get("authorization_reference"),
                    "authorization_basis": lease.get("authorization_basis"),
                    "capability_authorization_profile": lease.get("capability_authorization_profile"),
                    "capability_inherited_from_owner_root": bool(lease.get("capability_inherited_from_owner_root", False)),
                    "source_lease_id": lease.get("lease_id"),
                    "source_lease_expires_at": lease.get("expires_at"),
                    "execution_mode": mode,
                    "registered_executor_required": registered_executor_required,
                    "authority_minted_by_world": False,
                    "credential_minted_by_world": False,
                    "scope_expansion": False,
                }
            )
    return intents


def _network_summary(network_dir: Path, *, now: int) -> tuple[dict[str, Any], Path | None]:
    runtime_path = _first(network_dir, "runtime-final.json", "network_policy_runtime.json")
    replicas_path = _first(network_dir, "replicas-final.json")
    apply_path = _first(network_dir, "apply-audit-pass3.json", "apply-audit-pass2.json")
    runtime = _read_json(runtime_path, {}) if runtime_path else {}
    replicas = _read_json(replicas_path, {}) if replicas_path else {}
    apply = _read_json(apply_path, {}) if apply_path else {}

    grants = runtime.get("grants", {}) if isinstance(runtime, Mapping) else {}
    replica_rows = replicas.get("replicas", []) if isinstance(replicas, Mapping) else []
    summary = {
        "evidence_present": runtime_path is not None,
        "runtime_grant_count": len(grants) if isinstance(grants, Mapping) else 0,
        "persistent_replica_count": len(replica_rows) if isinstance(replica_rows, list) else 0,
        "external_attempted": int(apply.get("attempted", 0) or 0) if isinstance(apply, Mapping) else 0,
        "external_succeeded": int(apply.get("succeeded", 0) or 0) if isinstance(apply, Mapping) else 0,
        "persistence_backend": replicas.get("persistence_backend") if isinstance(replicas, Mapping) else None,
        "authority_expansion": replicas.get("authority_expansion") if isinstance(replicas, Mapping) else None,
        "evidence_age_seconds": _age_seconds(runtime_path, now=now),
    }
    return summary, runtime_path


def _recovery_summary(recovery_dir: Path, *, now: int) -> tuple[dict[str, Any], Path | None]:
    path = _first(recovery_dir, "external-recovery-report.json")
    report = _read_json(path, {}) if path else {}
    feedback = report.get("guard_feedback", {}) if isinstance(report, Mapping) else {}
    summary = {
        "evidence_present": path is not None,
        "closed_loop_recovery": bool(report.get("closed_loop_recovery", False)) if isinstance(report, Mapping) else False,
        "attempted_missions": int(report.get("attempted_missions", 0) or 0) if isinstance(report, Mapping) else 0,
        "transport_attempts": int(report.get("transport_attempts", 0) or 0) if isinstance(report, Mapping) else 0,
        "authority_preserved": bool(report.get("authority_preserved", False)) if isinstance(report, Mapping) else False,
        "self_tune_pressure": int(feedback.get("self_tune_pressure", 0) or 0) if isinstance(feedback, Mapping) else 0,
        "pressure_level": feedback.get("pressure_level") if isinstance(feedback, Mapping) else None,
        "external_retry_allowed": bool(feedback.get("external_retry_allowed", False)) if isinstance(feedback, Mapping) else False,
        "boundary_bypass_enabled": bool(feedback.get("boundary_bypass_enabled", False)) if isinstance(feedback, Mapping) else False,
        "evidence_age_seconds": _age_seconds(path, now=now),
    }
    return summary, path


def _continuity_summary(continuity_dir: Path, *, now: int) -> tuple[dict[str, Any], Path | None]:
    path = _first(continuity_dir, "latest-run.json")
    report = _read_json(path, {}) if path else {}
    targets = report.get("targets", []) if isinstance(report, Mapping) else []
    successful_dispatches = 0
    deployed_targets: list[str] = []
    for row in targets if isinstance(targets, list) else []:
        if not isinstance(row, Mapping):
            continue
        receipt = row.get("deployment_receipt", {})
        if isinstance(receipt, Mapping) and receipt.get("success") is True:
            successful_dispatches += 1
            target = str(row.get("target_host") or "").strip()
            if target:
                deployed_targets.append(target)
    summary = {
        "evidence_present": path is not None,
        "targets_processed": int(report.get("targets_processed", 0) or 0) if isinstance(report, Mapping) else 0,
        "successful_deployment_dispatches": successful_dispatches,
        "deployed_targets": sorted(set(deployed_targets)),
        "evidence_age_seconds": _age_seconds(path, now=now),
    }
    return summary, path


def _security_summary(repo_root: Path, *, now: int) -> tuple[dict[str, Any], Path | None]:
    path = repo_root / "security" / "runtime" / "ai_security_state.json"
    if not path.exists():
        return {
            "evidence_present": False,
            "mode": "consume_existing_security_state_only",
            "evidence_age_seconds": None,
        }, None
    state = _read_json(path, {})
    summary = {
        "evidence_present": isinstance(state, Mapping),
        "mode": "consume_existing_security_state_only",
        "schema": state.get("schema") if isinstance(state, Mapping) else None,
        "generation": state.get("generation") if isinstance(state, Mapping) else None,
        "evidence_age_seconds": _age_seconds(path, now=now),
    }
    return summary, path


def _handoffs(
    evidence_paths: Mapping[str, Path | None],
    *,
    stale_after: Mapping[str, int],
    now: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component, workflow in WORKFLOW_HANDOFFS.items():
        path = evidence_paths.get(component)
        age = _age_seconds(path, now=now)
        threshold = max(300, int(stale_after.get(component, DEFAULT_STALE_AFTER[component])))
        reason = None
        if path is None:
            reason = "evidence_missing"
        elif age is not None and age > threshold:
            reason = "evidence_stale"
        rows.append(
            {
                "component": component,
                "workflow": workflow,
                "dispatch": reason is not None,
                "reason": reason,
                "evidence_age_seconds": age,
                "stale_after_seconds": threshold,
                "authority_change_requested": False,
            }
        )
    return rows


def build_world_trust_root_checkpoint(
    *,
    repo_root: str | Path,
    shared_state_dir: str | Path,
    network_state_dir: str | Path,
    recovery_state_dir: str | Path,
    continuity_state_dir: str | Path,
    output_dir: str | Path,
    config_path: str | Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Join the current production loops into one durable WORLD checkpoint."""
    current = int(time.time()) if now is None else int(now)
    root = Path(repo_root)
    shared = Path(shared_state_dir)
    network = Path(network_state_dir)
    recovery = Path(recovery_state_dir)
    continuity = Path(continuity_state_dir)
    out = Path(output_dir)
    config = _load_config(Path(config_path) if config_path is not None else None)

    trust_root_id = str(config.get("trust_root_id") or DEFAULT_TRUST_ROOT_ID).strip()
    if not trust_root_id:
        raise WorldTrustRootError("trust_root_id is required")
    actors = sorted({str(x).strip().upper() for x in config.get("actors", DEFAULT_ACTORS) if str(x).strip()})
    stale_after_raw = config.get("stale_after_seconds", {})
    stale_after = dict(DEFAULT_STALE_AFTER)
    if isinstance(stale_after_raw, Mapping):
        for key in DEFAULT_STALE_AFTER:
            if key in stale_after_raw:
                stale_after[key] = max(300, int(stale_after_raw[key]))

    leases = _active_leases(shared, now=current)
    intents = _execution_intents(leases, trust_root_id=trust_root_id, now=current)
    authority_references = sorted({str(row["authorization_reference"]) for row in leases})
    credential_scopes = sorted({str(row["credential_scope"]) for row in leases if str(row["credential_scope"]) != "none"})

    network_summary, network_path = _network_summary(network, now=current)
    recovery_summary, recovery_path = _recovery_summary(recovery, now=current)
    continuity_summary, continuity_path = _continuity_summary(continuity, now=current)
    security_summary, _ = _security_summary(root, now=current)
    shared_path = shared / "discovery_capability_leases.json"
    if not shared_path.exists():
        shared_path = None

    handoffs = _handoffs(
        {
            "shared_discovery": shared_path,
            "network_policy": network_path,
            "external_recovery": recovery_path,
            "production_continuity": continuity_path,
        },
        stale_after=stale_after,
        now=current,
    )

    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "environment": "production",
        "generated_at": current,
        "trust_root_id": trust_root_id,
        "trust_root_semantics": "aggregate_existing_owner_authority_evidence_without_minting_new_authority",
        "lineage_id": f"{trust_root_id}:{current // 900}",
        "actors": actors,
        "closed_loop": True,
        "phases": ["discover", "authorize", "act", "replicate", "persist", "recover", "discover_again"],
        "authorization": {
            "active_capability_lease_count": len(leases),
            "authority_references": authority_references,
            "credential_scope_names": credential_scopes,
            "authority_minted_by_world": False,
            "credential_minted_by_world": False,
            "auto_renew_source": "existing_discovery_capability_lease_engine",
        },
        "execution": {
            "intent_count": len(intents),
            "high_impact_intent_count": sum(1 for row in intents if row["high_impact"]),
            "credentialed_intent_count": sum(1 for row in intents if row["capability"] == "credentialed_action"),
            "high_impact_requires_registered_executor": True,
        },
        "replication_persistence": network_summary,
        "self_tuning_recovery": recovery_summary,
        "deployment_continuity": continuity_summary,
        "security": security_summary,
        "network_policy_self_edit": "consume_existing_authority-preserving_runtime_policy_only",
        "security_self_approval": "consume_existing_delegated_or_independently_approved_security_state_only",
        "boundary_denial_becomes_authority": False,
        "raw_credential_replication": False,
        "handoff_dispatch_count": sum(1 for row in handoffs if row["dispatch"]),
    }

    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "world_trust_root_checkpoint.json", checkpoint)
    _write_json(
        out / "world_execution_intents.json",
        {
            "schema": INTENT_SCHEMA,
            "generated_at": current,
            "trust_root_id": trust_root_id,
            "intents": intents,
        },
    )
    _write_json(
        out / "world_handoffs.json",
        {
            "schema": HANDOFF_SCHEMA,
            "generated_at": current,
            "trust_root_id": trust_root_id,
            "handoffs": handoffs,
        },
    )
    return checkpoint
