"""Finalize WORLD v2 reporting so every component age uses source-run provenance.

The underlying legacy coordinator still exposes local-file mtime ages for compatibility.
The hardening layer correctly uses source workflow timestamps for handoff decisions; this
finalizer also replaces the human/machine-facing summary ages so the checkpoint cannot
present contradictory freshness data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from engine.world_trust_root_hardening import build_hardened_world_trust_root_checkpoint

FINALIZER_CONTRACT = "world-trust-root-provenance-reporting/v1"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _digest(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("checkpoint_digest", None)
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bind_summary(summary: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(summary),
        "evidence_age_seconds": evidence.get("source_age_seconds"),
        "freshness_basis": evidence.get("freshness_basis"),
        "source_run_id": evidence.get("source_run_id"),
        "source_head_sha": evidence.get("source_head_sha"),
        "evidence_digest": evidence.get("evidence_digest"),
    }


def build_provenance_finalized_world_checkpoint(**kwargs: Any) -> dict[str, Any]:
    checkpoint = build_hardened_world_trust_root_checkpoint(**kwargs)
    out = Path(kwargs["output_dir"])
    manifest = _read(out / "world_evidence_manifest.json")
    components = manifest.get("components", {}) if isinstance(manifest, Mapping) else {}

    checkpoint["authorization"] = _bind_summary(
        checkpoint.get("authorization", {}),
        components.get("shared_discovery", {}) if isinstance(components, Mapping) else {},
    )
    checkpoint["replication_persistence"] = _bind_summary(
        checkpoint.get("replication_persistence", {}),
        components.get("network_policy", {}) if isinstance(components, Mapping) else {},
    )
    checkpoint["self_tuning_recovery"] = _bind_summary(
        checkpoint.get("self_tuning_recovery", {}),
        components.get("external_recovery", {}) if isinstance(components, Mapping) else {},
    )
    checkpoint["deployment_continuity"] = _bind_summary(
        checkpoint.get("deployment_continuity", {}),
        components.get("production_continuity", {}) if isinstance(components, Mapping) else {},
    )

    security = dict(checkpoint.get("security", {}))
    security_manifest = manifest.get("security_state", {}) if isinstance(manifest, Mapping) else {}
    security["freshness_basis"] = "repository_snapshot_sha256"
    security["evidence_digest"] = security_manifest.get("sha256") if isinstance(security_manifest, Mapping) else None
    checkpoint["security"] = security
    checkpoint["evidence_age_semantics"] = "source_workflow_updated_at"
    checkpoint["provenance_reporting_contract"] = FINALIZER_CONTRACT
    checkpoint["checkpoint_digest"] = _digest(checkpoint)

    chain = _read(out / "world_checkpoint_chain.json")
    if chain:
        chain["checkpoint_digest"] = checkpoint["checkpoint_digest"]
        chain["provenance_reporting_contract"] = FINALIZER_CONTRACT
        _write(out / "world_checkpoint_chain.json", chain)
    _write(out / "world_trust_root_checkpoint.json", checkpoint)
    return checkpoint
