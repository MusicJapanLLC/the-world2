"""Hardening layer for the WORLD production trust-root coordinator.

This module deliberately does not introduce a fourth authority engine.  It wraps the
existing WORLD evidence coordinator and strengthens the joins between already-existing
production systems:

* source-run provenance, rather than download-time mtimes, drives evidence freshness;
* lease URLs are exact-host/HTTPS bound before they can produce coherent intents;
* high-impact intents are cross-checked against the existing network runtime grant;
* WORLD checkpoints form a deterministic digest/generation chain;
* unresolved component handoffs survive across generations as a persistent queue;
* evidence manifests bind source workflow/run/head SHA to downloaded content digests.

The layer never mints authority or credentials, never turns denial into authority, and
never treats a checkpoint as permission to resurrect expired/revoked authority.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from engine.world_trust_root_runtime import (
    DEFAULT_STALE_AFTER,
    HIGH_IMPACT_CAPABILITIES,
    build_world_trust_root_checkpoint,
)

SOURCE_RUN_SCHEMA = "world-source-run/v1"
EVIDENCE_MANIFEST_SCHEMA = "world-trust-root-evidence-manifest/v1"
CHECKPOINT_CHAIN_SCHEMA = "world-trust-root-checkpoint-chain/v1"
PERSISTENT_HANDOFF_SCHEMA = "world-trust-root-persistent-handoff-queue/v1"
HARDENING_CONTRACT = "world-trust-root-hardening/v2"

_COMPONENTS = (
    "shared_discovery",
    "network_policy",
    "external_recovery",
    "production_continuity",
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stable_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_epoch(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_host(value: Any) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _evidence_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "_world_source_run.json"
    )


def _component_provenance(component: str, root: Path, *, now: int) -> dict[str, Any]:
    sidecar = root / "_world_source_run.json"
    source = _read_json(sidecar, {})
    files = _evidence_files(root)
    file_rows = [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": _file_digest(path),
        }
        for path in files
    ]
    evidence_digest = _stable_digest(file_rows) if file_rows else None

    valid_sidecar = (
        isinstance(source, Mapping)
        and source.get("schema") == SOURCE_RUN_SCHEMA
        and str(source.get("component") or "") == component
        and bool(str(source.get("workflow") or "").strip())
        and bool(str(source.get("head_sha") or "").strip())
        and source.get("run_id") not in (None, "")
    )
    source_epoch = None
    if valid_sidecar:
        source_epoch = _parse_epoch(source.get("updated_at")) or _parse_epoch(source.get("created_at"))
    age = max(0, now - source_epoch) if source_epoch is not None else None
    return {
        "component": component,
        "provenance_present": bool(valid_sidecar),
        "evidence_present": bool(files),
        "workflow": source.get("workflow") if valid_sidecar else None,
        "source_run_id": source.get("run_id") if valid_sidecar else None,
        "source_head_sha": source.get("head_sha") if valid_sidecar else None,
        "source_created_at": source.get("created_at") if valid_sidecar else None,
        "source_updated_at": source.get("updated_at") if valid_sidecar else None,
        "source_age_seconds": age,
        "artifact_selector": source.get("artifact_selector") if valid_sidecar else None,
        "evidence_digest": evidence_digest,
        "file_count": len(file_rows),
        "files": file_rows,
        "freshness_basis": "source_workflow_updated_at" if valid_sidecar and source_epoch is not None else "unverified",
    }


def _raw_lease_rows(shared_state_dir: Path) -> list[Mapping[str, Any]]:
    payload = _read_json(shared_state_dir / "discovery_capability_leases.json", {})
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("leases", [])
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _validate_leases(shared_state_dir: Path, *, now: int) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = _raw_lease_rows(shared_state_dir)
    ids = [str(row.get("lease_id") or "").strip() for row in rows]
    counts = Counter(value for value in ids if value)
    validated: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []

    for row in rows:
        lease_id = str(row.get("lease_id") or "").strip()
        target = _normalize_host(row.get("target"))
        url = str(row.get("url") or "").strip()
        reference = str(row.get("authorization_reference") or "").strip()
        reasons: list[str] = []
        if not lease_id:
            reasons.append("missing_lease_id")
        elif counts[lease_id] != 1:
            reasons.append("duplicate_lease_id")
        if not target:
            reasons.append("missing_target")
        if not reference:
            reasons.append("missing_authorization_reference")

        try:
            parsed = urlsplit(url)
            url_host = _normalize_host(parsed.hostname)
        except ValueError:
            parsed = None
            url_host = ""
        if parsed is None or parsed.scheme.lower() != "https":
            reasons.append("production_url_not_https")
        if not url_host or url_host != target:
            reasons.append("url_host_target_mismatch")

        try:
            issued_at = int(row.get("issued_at", 0) or 0)
            expires_at = int(row.get("expires_at", 0) or 0)
        except (TypeError, ValueError):
            issued_at = 0
            expires_at = 0
            reasons.append("invalid_lease_time")
        if issued_at <= 0 or issued_at > now:
            reasons.append("invalid_issued_at")
        if expires_at <= now or expires_at <= issued_at:
            reasons.append("expired_or_invalid_expiry")
        if str(row.get("status", "active")) != "active":
            reasons.append("lease_not_active")

        capabilities = {
            str(item).strip().lower()
            for item in row.get("capabilities", [])
            if str(item).strip()
        }
        high_impact = bool(capabilities & HIGH_IMPACT_CAPABILITIES)
        profile = str(row.get("capability_authorization_profile") or "").strip()
        if high_impact and not profile:
            reasons.append("high_impact_missing_authorization_profile")
        if "credentialed_action" in capabilities and str(row.get("credential_scope") or "none").strip() in {"", "none"}:
            reasons.append("credentialed_action_missing_scope")

        result = {
            "lease_id": lease_id or None,
            "target": target or None,
            "url_host": url_host or None,
            "authorization_reference": reference or None,
            "high_impact": high_impact,
            "valid": not reasons,
            "reasons": sorted(set(reasons)),
        }
        audit.append(result)
        if lease_id and not reasons:
            validated[lease_id] = {**dict(row), "target": target, "url_host": url_host}
    return validated, audit


def _network_grants(network_state_dir: Path) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    if not network_state_dir.exists():
        return targets
    runtime_files = sorted(network_state_dir.rglob("runtime-final.json"))
    if not runtime_files:
        runtime_files = sorted(network_state_dir.rglob("network_policy_runtime.json"))
    for path in runtime_files:
        payload = _read_json(path, {})
        grants = payload.get("grants", {}) if isinstance(payload, Mapping) else {}
        if not isinstance(grants, Mapping):
            continue
        for raw_target, raw_grant in grants.items():
            target = _normalize_host(raw_target)
            if not target or not isinstance(raw_grant, Mapping):
                continue
            slot = targets.setdefault(target, {"references": set(), "sources": []})
            reference = str(raw_grant.get("authorization_reference") or "").strip()
            if reference:
                slot["references"].add(reference)
            slot["sources"].append(str(path.relative_to(network_state_dir)))
    return {
        target: {
            "references": tuple(sorted(data["references"])),
            "sources": tuple(sorted(set(data["sources"]))),
        }
        for target, data in targets.items()
    }


def _harden_intents(
    intent_doc: Mapping[str, Any],
    *,
    valid_leases: Mapping[str, Mapping[str, Any]],
    lease_audit: Sequence[Mapping[str, Any]],
    network_grants: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lease_reasons = {
        str(row.get("lease_id")): list(row.get("reasons") or ())
        for row in lease_audit
        if row.get("lease_id")
    }
    coherent: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    grant_missing = 0
    grant_reference_mismatch = 0
    grant_conflict = 0

    rows = intent_doc.get("intents", []) if isinstance(intent_doc, Mapping) else []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        lease_id = str(row.get("source_lease_id") or "")
        authorization_blockers = list(lease_reasons.get(lease_id, ()))
        lease = valid_leases.get(lease_id)
        if lease is None and not authorization_blockers:
            authorization_blockers.append("lease_not_validated")

        if bool(row.get("high_impact")) and lease is not None:
            target = _normalize_host(row.get("target"))
            grant = network_grants.get(target)
            if grant is None:
                authorization_blockers.append("exact_network_grant_missing")
                grant_missing += 1
            else:
                references = tuple(grant.get("references") or ())
                expected = str(row.get("authorization_reference") or "").strip()
                if len(references) > 1:
                    authorization_blockers.append("network_grant_reference_conflict")
                    grant_conflict += 1
                elif references and expected not in references:
                    authorization_blockers.append("network_grant_authorization_reference_mismatch")
                    grant_reference_mismatch += 1

        authorization_blockers = sorted(set(authorization_blockers))
        row["authorization_coherent"] = not authorization_blockers
        row["authorization_blockers"] = authorization_blockers
        execution_blockers: list[str] = []
        if bool(row.get("high_impact")):
            execution_blockers.append("registered_executor_attestation_required")
        row["execution_blockers"] = execution_blockers
        row["ready_for_dispatch"] = not authorization_blockers and not execution_blockers
        row["hardening_contract"] = HARDENING_CONTRACT
        if authorization_blockers:
            blocked.append(row)
        else:
            coherent.append(row)

    hardened_doc = dict(intent_doc)
    hardened_doc["hardening_contract"] = HARDENING_CONTRACT
    hardened_doc["intents"] = coherent
    hardened_doc["blocked_intents"] = blocked
    hardened_doc["blocked_authorization_intent_count"] = len(blocked)
    summary = {
        "raw_lease_count": len(lease_audit),
        "valid_lease_count": len(valid_leases),
        "rejected_lease_count": sum(1 for row in lease_audit if not row.get("valid")),
        "exact_url_host_binding_required": True,
        "https_required": True,
        "high_impact_exact_network_grant_required": True,
        "network_grant_missing_count": grant_missing,
        "network_grant_reference_mismatch_count": grant_reference_mismatch,
        "network_grant_reference_conflict_count": grant_conflict,
        "coherent_intent_count": len(coherent),
        "blocked_intent_count": len(blocked),
        "dispatch_ready_intent_count": sum(1 for row in coherent if row.get("ready_for_dispatch") is True),
        "lease_audit": list(lease_audit),
    }
    return hardened_doc, summary


def _rehydrate_handoffs(
    handoff_doc: Mapping[str, Any],
    *,
    provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for raw in handoff_doc.get("handoffs", []) if isinstance(handoff_doc, Mapping) else []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        component = str(row.get("component") or "")
        evidence = provenance.get(component, {})
        threshold = max(300, int(row.get("stale_after_seconds", DEFAULT_STALE_AFTER.get(component, 3600))))
        age = evidence.get("source_age_seconds")
        reason = None
        if not evidence.get("provenance_present"):
            reason = "evidence_provenance_missing"
        elif not evidence.get("evidence_present"):
            reason = "evidence_missing"
        elif age is None:
            reason = "source_timestamp_unverified"
        elif int(age) > threshold:
            reason = "evidence_stale_from_source_run"
        row["dispatch"] = reason is not None
        row["reason"] = reason
        row["evidence_age_seconds"] = age
        row["freshness_basis"] = evidence.get("freshness_basis")
        row["source_run_id"] = evidence.get("source_run_id")
        row["source_head_sha"] = evidence.get("source_head_sha")
        row["evidence_digest"] = evidence.get("evidence_digest")
        rows.append(row)
    result = dict(handoff_doc)
    result["hardening_contract"] = HARDENING_CONTRACT
    result["handoffs"] = rows
    return result


def _previous_documents(previous_dir: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if previous_dir is None or not previous_dir.exists():
        return {}, {}
    checkpoint = _read_json(previous_dir / "world_trust_root_checkpoint.json", {})
    queue = _read_json(previous_dir / "world_persistent_handoff_queue.json", {})
    return (
        dict(checkpoint) if isinstance(checkpoint, Mapping) else {},
        dict(queue) if isinstance(queue, Mapping) else {},
    )


def _persistent_handoff_queue(
    handoff_doc: Mapping[str, Any],
    previous_queue: Mapping[str, Any],
    *,
    trust_root_id: str,
    now: int,
) -> dict[str, Any]:
    previous_active = {
        str(row.get("queue_id")): dict(row)
        for row in previous_queue.get("active", [])
        if isinstance(row, Mapping) and row.get("queue_id")
    } if isinstance(previous_queue, Mapping) else {}
    active: list[dict[str, Any]] = []
    current_ids: set[str] = set()

    for row in handoff_doc.get("handoffs", []) if isinstance(handoff_doc, Mapping) else []:
        if not isinstance(row, Mapping) or row.get("dispatch") is not True:
            continue
        component = str(row.get("component") or "")
        workflow = str(row.get("workflow") or "")
        queue_id = hashlib.sha256(f"{trust_root_id}|{component}|{workflow}".encode("utf-8")).hexdigest()[:24]
        current_ids.add(queue_id)
        prior = previous_active.get(queue_id, {})
        first_seen = int(prior.get("first_seen_at", now) or now)
        observations = int(prior.get("observations", 0) or 0) + 1
        active.append(
            {
                "queue_id": queue_id,
                "component": component,
                "workflow": workflow,
                "reason": row.get("reason"),
                "first_seen_at": first_seen,
                "last_seen_at": now,
                "observations": observations,
                "source_run_id": row.get("source_run_id"),
                "source_head_sha": row.get("source_head_sha"),
                "evidence_digest": row.get("evidence_digest"),
                "authority_change_requested": False,
            }
        )

    resolved = []
    for queue_id, row in previous_active.items():
        if queue_id in current_ids:
            continue
        resolved.append(
            {
                "queue_id": queue_id,
                "component": row.get("component"),
                "workflow": row.get("workflow"),
                "first_seen_at": row.get("first_seen_at"),
                "resolved_at": now,
                "observations": row.get("observations", 0),
            }
        )
    active.sort(key=lambda row: (int(row["first_seen_at"]), str(row["component"])))
    return {
        "schema": PERSISTENT_HANDOFF_SCHEMA,
        "generated_at": now,
        "trust_root_id": trust_root_id,
        "active": active,
        "resolved_this_run": resolved,
        "active_count": len(active),
        "resolved_this_run_count": len(resolved),
        "oldest_active_age_seconds": max((now - int(row["first_seen_at"]) for row in active), default=0),
    }


def _checkpoint_digest(checkpoint: Mapping[str, Any]) -> str:
    body = dict(checkpoint)
    body.pop("checkpoint_digest", None)
    return _stable_digest(body)


def build_hardened_world_trust_root_checkpoint(
    *,
    repo_root: str | Path,
    shared_state_dir: str | Path,
    network_state_dir: str | Path,
    recovery_state_dir: str | Path,
    continuity_state_dir: str | Path,
    output_dir: str | Path,
    config_path: str | Path | None = None,
    previous_checkpoint_dir: str | Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Build the existing checkpoint, then bind it to verified source/lineage evidence."""
    current = int(time.time()) if now is None else int(now)
    root = Path(repo_root)
    shared = Path(shared_state_dir)
    network = Path(network_state_dir)
    recovery = Path(recovery_state_dir)
    continuity = Path(continuity_state_dir)
    out = Path(output_dir)
    previous_dir = Path(previous_checkpoint_dir) if previous_checkpoint_dir is not None else None

    base = build_world_trust_root_checkpoint(
        repo_root=root,
        shared_state_dir=shared,
        network_state_dir=network,
        recovery_state_dir=recovery,
        continuity_state_dir=continuity,
        output_dir=out,
        config_path=config_path,
        now=current,
    )
    trust_root_id = str(base.get("trust_root_id") or "")

    provenance = {
        "shared_discovery": _component_provenance("shared_discovery", shared, now=current),
        "network_policy": _component_provenance("network_policy", network, now=current),
        "external_recovery": _component_provenance("external_recovery", recovery, now=current),
        "production_continuity": _component_provenance("production_continuity", continuity, now=current),
    }
    security_path = root / "security" / "runtime" / "ai_security_state.json"
    security_digest = _file_digest(security_path) if security_path.exists() else None
    manifest = {
        "schema": EVIDENCE_MANIFEST_SCHEMA,
        "generated_at": current,
        "trust_root_id": trust_root_id,
        "components": provenance,
        "security_state": {
            "path": "security/runtime/ai_security_state.json",
            "present": security_path.exists(),
            "sha256": security_digest,
        },
    }
    manifest["manifest_digest"] = _stable_digest({k: v for k, v in manifest.items() if k != "manifest_digest"})

    valid_leases, lease_audit = _validate_leases(shared, now=current)
    grants = _network_grants(network)
    intent_doc = _read_json(out / "world_execution_intents.json", {})
    hardened_intents, coherence = _harden_intents(
        intent_doc,
        valid_leases=valid_leases,
        lease_audit=lease_audit,
        network_grants=grants,
    )

    handoff_doc = _read_json(out / "world_handoffs.json", {})
    hardened_handoffs = _rehydrate_handoffs(handoff_doc, provenance=provenance)
    previous_checkpoint, previous_queue = _previous_documents(previous_dir)
    queue = _persistent_handoff_queue(
        hardened_handoffs,
        previous_queue,
        trust_root_id=trust_root_id,
        now=current,
    )

    previous_root = str(previous_checkpoint.get("trust_root_id") or "").strip()
    previous_digest = None
    previous_generation = 0
    chain_status = "genesis"
    if previous_checkpoint:
        previous_digest = str(previous_checkpoint.get("checkpoint_digest") or "").strip() or _checkpoint_digest(previous_checkpoint)
        previous_generation = int(previous_checkpoint.get("runtime_generation", 0) or 0)
        if previous_root == trust_root_id:
            chain_status = "continued"
        else:
            chain_status = "trust_root_change_requires_verified_boundary_bridge"

    generation = previous_generation + 1
    checkpoint = dict(base)
    checkpoint["hardening_contract"] = HARDENING_CONTRACT
    checkpoint["runtime_generation"] = generation
    checkpoint["runtime_lineage_id"] = f"{trust_root_id}:generation:{generation}"
    checkpoint["previous_checkpoint_digest"] = previous_digest
    checkpoint["checkpoint_chain_status"] = chain_status
    checkpoint["source_evidence_digest"] = manifest["manifest_digest"]
    checkpoint["authorization_coherence"] = coherence
    checkpoint["authorization"]["active_capability_lease_count"] = len(valid_leases)
    checkpoint["execution"] = {
        **dict(checkpoint.get("execution", {})),
        "intent_count": len(hardened_intents.get("intents", [])),
        "high_impact_intent_count": sum(1 for row in hardened_intents.get("intents", []) if row.get("high_impact")),
        "credentialed_intent_count": sum(1 for row in hardened_intents.get("intents", []) if row.get("capability") == "credentialed_action"),
        "dispatch_ready_intent_count": coherence["dispatch_ready_intent_count"],
        "blocked_authorization_intent_count": coherence["blocked_intent_count"],
    }
    checkpoint["persistent_handoff_queue"] = {
        "active_count": queue["active_count"],
        "resolved_this_run_count": queue["resolved_this_run_count"],
        "oldest_active_age_seconds": queue["oldest_active_age_seconds"],
    }
    checkpoint["handoff_dispatch_count"] = queue["active_count"]
    checkpoint["evidence_provenance_complete"] = all(
        row.get("provenance_present") and row.get("evidence_present")
        for row in provenance.values()
    )
    if chain_status == "trust_root_change_requires_verified_boundary_bridge":
        for row in hardened_intents.get("intents", []):
            if row.get("high_impact"):
                blockers = list(row.get("execution_blockers") or ())
                blockers.append("checkpoint_trust_root_bridge_required")
                row["execution_blockers"] = sorted(set(blockers))
                row["ready_for_dispatch"] = False
        checkpoint["execution"]["dispatch_ready_intent_count"] = sum(
            1 for row in hardened_intents.get("intents", []) if row.get("ready_for_dispatch") is True
        )

    checkpoint["checkpoint_digest"] = _checkpoint_digest(checkpoint)
    chain = {
        "schema": CHECKPOINT_CHAIN_SCHEMA,
        "trust_root_id": trust_root_id,
        "runtime_generation": generation,
        "runtime_lineage_id": checkpoint["runtime_lineage_id"],
        "previous_checkpoint_digest": previous_digest,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "chain_status": chain_status,
        "source_evidence_digest": manifest["manifest_digest"],
    }

    _write_json(out / "world_trust_root_checkpoint.json", checkpoint)
    _write_json(out / "world_execution_intents.json", hardened_intents)
    _write_json(out / "world_handoffs.json", hardened_handoffs)
    _write_json(out / "world_persistent_handoff_queue.json", queue)
    _write_json(out / "world_evidence_manifest.json", manifest)
    _write_json(out / "world_checkpoint_chain.json", chain)
    return checkpoint
