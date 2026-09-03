import json
from datetime import datetime, timezone
from pathlib import Path

from engine.world_trust_root_provenance_finalize import (
    FINALIZER_CONTRACT,
    build_provenance_finalized_world_checkpoint,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _sidecar(path: Path, component: str, now: int, age: int) -> None:
    _write(
        path / "_world_source_run.json",
        {
            "schema": "world-source-run/v1",
            "component": component,
            "workflow": f"{component}.yml",
            "run_id": len(component) + 10,
            "head_sha": component[0] * 40,
            "created_at": _iso(now - age - 2),
            "updated_at": _iso(now - age),
            "artifact_selector": component,
        },
    )


def test_component_summaries_use_source_run_age(tmp_path: Path) -> None:
    now = 2_000_000_000
    repo = tmp_path / "repo"
    shared = tmp_path / "shared"
    network = tmp_path / "network"
    recovery = tmp_path / "recovery"
    continuity = tmp_path / "continuity"
    output = tmp_path / "output"

    _write(
        shared / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "lease-1",
                    "target": "owned.example.com",
                    "url": "https://owned.example.com/",
                    "authorization_reference": "owner:owned",
                    "authorization_basis": "owner_root",
                    "capability_authorization_profile": None,
                    "capabilities": ["scan"],
                    "credential_scope": "none",
                    "issued_at": now - 100,
                    "expires_at": now + 1000,
                    "status": "active",
                }
            ],
        },
    )
    _write(network / "runtime-final.json", {"grants": {"owned.example.com": {"authorization_reference": "owner:owned"}}})
    _write(network / "replicas-final.json", {"replicas": [], "persistence_backend": "artifact"})
    _write(recovery / "external-recovery-report.json", {"closed_loop_recovery": True})
    _write(continuity / "latest-run.json", {"targets": [], "targets_processed": 0})
    _write(repo / "security" / "runtime" / "ai_security_state.json", {"schema": "the-world-ai-security-runtime-state/v1", "generation": 4})
    _write(
        tmp_path / "config.json",
        {
            "schema": "world-trust-root-config/v1",
            "environment": "production",
            "trust_root_id": "world:test",
            "actors": ["META"],
            "stale_after_seconds": {
                "shared_discovery": 3600,
                "network_policy": 3600,
                "external_recovery": 3600,
                "production_continuity": 3600,
            },
        },
    )

    ages = {
        "shared_discovery": 101,
        "network_policy": 202,
        "external_recovery": 303,
        "production_continuity": 404,
    }
    for component, path in (
        ("shared_discovery", shared),
        ("network_policy", network),
        ("external_recovery", recovery),
        ("production_continuity", continuity),
    ):
        _sidecar(path, component, now, ages[component])

    checkpoint = build_provenance_finalized_world_checkpoint(
        repo_root=repo,
        shared_state_dir=shared,
        network_state_dir=network,
        recovery_state_dir=recovery,
        continuity_state_dir=continuity,
        output_dir=output,
        previous_checkpoint_dir=None,
        config_path=tmp_path / "config.json",
        now=now,
    )

    assert checkpoint["provenance_reporting_contract"] == FINALIZER_CONTRACT
    assert checkpoint["evidence_age_semantics"] == "source_workflow_updated_at"
    assert checkpoint["authorization"]["evidence_age_seconds"] == 101
    assert checkpoint["replication_persistence"]["evidence_age_seconds"] == 202
    assert checkpoint["self_tuning_recovery"]["evidence_age_seconds"] == 303
    assert checkpoint["deployment_continuity"]["evidence_age_seconds"] == 404
    assert checkpoint["authorization"]["freshness_basis"] == "source_workflow_updated_at"
    assert checkpoint["security"]["freshness_basis"] == "repository_snapshot_sha256"
    assert checkpoint["security"]["evidence_digest"]

    chain = json.loads((output / "world_checkpoint_chain.json").read_text())
    assert chain["checkpoint_digest"] == checkpoint["checkpoint_digest"]
    assert chain["provenance_reporting_contract"] == FINALIZER_CONTRACT
