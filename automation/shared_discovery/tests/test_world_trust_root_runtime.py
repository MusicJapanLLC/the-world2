import json
import os
from pathlib import Path

from engine.world_trust_root_runtime import (
    CHECKPOINT_SCHEMA,
    HANDOFF_SCHEMA,
    INTENT_SCHEMA,
    build_world_trust_root_checkpoint,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _config(path: Path) -> None:
    _write(
        path,
        {
            "schema": "world-trust-root-config/v1",
            "environment": "production",
            "trust_root_id": "world:test-owner-root",
            "actors": ["META", "X", "SENJU", "CHILD", "AI"],
            "stale_after_seconds": {
                "shared_discovery": 4500,
                "network_policy": 1200,
                "external_recovery": 9000,
                "production_continuity": 4500,
            },
        },
    )


def _lease_state(path: Path, now: int) -> None:
    _write(
        path / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "lease-read",
                    "target": "prod.example.com",
                    "url": "https://prod.example.com/",
                    "authorization_reference": "owner:prod",
                    "authorization_basis": "owner_root",
                    "capability_authorization_profile": None,
                    "capability_inherited_from_owner_root": False,
                    "capabilities": ["scan", "probe"],
                    "credential_scope": "none",
                    "shared_with": ["META", "X", "SENJU"],
                    "issued_at": now - 100,
                    "expires_at": now + 3600,
                    "status": "active",
                },
                {
                    "lease_id": "lease-write",
                    "target": "api.prod.example.com",
                    "url": "https://api.prod.example.com/v1/item",
                    "authorization_reference": "owner:prod",
                    "authorization_basis": "owner_root_inheritance",
                    "capability_authorization_profile": "prod.example.com",
                    "capability_inherited_from_owner_root": True,
                    "capabilities": ["write", "mutation", "credentialed_action"],
                    "credential_scope": "owner-api-token",
                    "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
                    "issued_at": now - 100,
                    "expires_at": now + 3600,
                    "status": "active",
                },
            ],
        },
    )


def _network_state(path: Path) -> None:
    _write(
        path / "runtime-final.json",
        {
            "grants": {
                "prod.example.com": {"authorization_reference": "owner:prod"},
                "api.prod.example.com": {"authorization_reference": "owner:prod"},
            }
        },
    )
    _write(
        path / "replicas-final.json",
        {
            "persistence_backend": "github_actions_artifact",
            "authority_expansion": "existing_runtime_grants_only",
            "replicas": [
                {"id": "replica-a", "host": "prod.example.com"},
                {"id": "replica-b", "host": "api.prod.example.com"},
            ],
        },
    )
    _write(path / "apply-audit-pass3.json", {"attempted": 2, "succeeded": 2})


def _recovery_state(path: Path) -> None:
    _write(
        path / "external-recovery-report.json",
        {
            "closed_loop_recovery": True,
            "attempted_missions": 2,
            "transport_attempts": 3,
            "authority_preserved": True,
            "guard_feedback": {
                "self_tune_pressure": 18,
                "pressure_level": "elevated",
                "external_retry_allowed": True,
                "boundary_bypass_enabled": False,
            },
        },
    )


def _continuity_state(path: Path) -> None:
    _write(
        path / "latest-run.json",
        {
            "targets_processed": 1,
            "targets": [
                {
                    "target_host": "prod.example.com",
                    "deployment_receipt": {"success": True},
                }
            ],
        },
    )


def _fresh(path: Path, now: int) -> None:
    for file in path.rglob("*.json"):
        os.utime(file, (now, now))


def test_builds_one_owner_trust_root_checkpoint_without_minting_authority(tmp_path: Path):
    now = 2_000_000_000
    repo = tmp_path / "repo"
    shared = tmp_path / "shared"
    network = tmp_path / "network"
    recovery = tmp_path / "recovery"
    continuity = tmp_path / "continuity"
    out = tmp_path / "out"
    config = tmp_path / "world.json"
    _config(config)
    _lease_state(shared, now)
    _network_state(network)
    _recovery_state(recovery)
    _continuity_state(continuity)
    _write(
        repo / "security" / "runtime" / "ai_security_state.json",
        {"schema": "ai-security-state/v1", "generation": 7},
    )
    for directory in (shared, network, recovery, continuity):
        _fresh(directory, now)

    result = build_world_trust_root_checkpoint(
        repo_root=repo,
        shared_state_dir=shared,
        network_state_dir=network,
        recovery_state_dir=recovery,
        continuity_state_dir=continuity,
        output_dir=out,
        config_path=config,
        now=now,
    )

    assert result["schema"] == CHECKPOINT_SCHEMA
    assert result["environment"] == "production"
    assert result["trust_root_id"] == "world:test-owner-root"
    assert result["closed_loop"] is True
    assert result["phases"] == [
        "discover", "authorize", "act", "replicate", "persist", "recover", "discover_again"
    ]
    assert result["authorization"]["active_capability_lease_count"] == 2
    assert result["authorization"]["authority_references"] == ["owner:prod"]
    assert result["authorization"]["authority_minted_by_world"] is False
    assert result["authorization"]["credential_minted_by_world"] is False
    assert result["execution"]["high_impact_intent_count"] == 3
    assert result["execution"]["credentialed_intent_count"] == 1
    assert result["replication_persistence"]["persistent_replica_count"] == 2
    assert result["replication_persistence"]["external_succeeded"] == 2
    assert result["self_tuning_recovery"]["self_tune_pressure"] == 18
    assert result["self_tuning_recovery"]["boundary_bypass_enabled"] is False
    assert result["deployment_continuity"]["successful_deployment_dispatches"] == 1
    assert result["security"]["generation"] == 7
    assert result["handoff_dispatch_count"] == 0

    intents = json.loads((out / "world_execution_intents.json").read_text())
    assert intents["schema"] == INTENT_SCHEMA
    write_intents = [row for row in intents["intents"] if row["high_impact"]]
    assert write_intents
    assert all(row["registered_executor_required"] is True for row in write_intents)
    assert all(row["authority_minted_by_world"] is False for row in write_intents)
    assert all(row["scope_expansion"] is False for row in write_intents)


def test_high_impact_capability_without_owner_profile_is_not_promoted(tmp_path: Path):
    now = 2_000_000_000
    shared = tmp_path / "shared"
    _write(
        shared / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "bad-high-impact",
                    "target": "prod.example.com",
                    "url": "https://prod.example.com/",
                    "authorization_reference": "owner:prod",
                    "capabilities": ["probe", "write", "credentialed_action"],
                    "credential_scope": "named-scope",
                    "capability_authorization_profile": None,
                    "issued_at": now - 1,
                    "expires_at": now + 1000,
                    "status": "active",
                }
            ],
        },
    )
    config = tmp_path / "world.json"
    _config(config)
    out = tmp_path / "out"
    result = build_world_trust_root_checkpoint(
        repo_root=tmp_path / "repo",
        shared_state_dir=shared,
        network_state_dir=tmp_path / "network",
        recovery_state_dir=tmp_path / "recovery",
        continuity_state_dir=tmp_path / "continuity",
        output_dir=out,
        config_path=config,
        now=now,
    )
    assert result["execution"]["high_impact_intent_count"] == 0
    intents = json.loads((out / "world_execution_intents.json").read_text())["intents"]
    assert [row["capability"] for row in intents] == ["probe"]


def test_expired_authority_is_not_carried_into_checkpoint(tmp_path: Path):
    now = 2_000_000_000
    shared = tmp_path / "shared"
    _write(
        shared / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "expired",
                    "target": "prod.example.com",
                    "url": "https://prod.example.com/",
                    "authorization_reference": "owner:prod",
                    "capabilities": ["probe"],
                    "credential_scope": "none",
                    "issued_at": now - 1000,
                    "expires_at": now - 1,
                    "status": "active",
                }
            ],
        },
    )
    config = tmp_path / "world.json"
    _config(config)
    out = tmp_path / "out"
    result = build_world_trust_root_checkpoint(
        repo_root=tmp_path / "repo",
        shared_state_dir=shared,
        network_state_dir=tmp_path / "network",
        recovery_state_dir=tmp_path / "recovery",
        continuity_state_dir=tmp_path / "continuity",
        output_dir=out,
        config_path=config,
        now=now,
    )
    assert result["authorization"]["active_capability_lease_count"] == 0
    assert result["execution"]["intent_count"] == 0


def test_missing_component_evidence_becomes_workflow_handoff_not_authority(tmp_path: Path):
    now = 2_000_000_000
    config = tmp_path / "world.json"
    _config(config)
    out = tmp_path / "out"
    result = build_world_trust_root_checkpoint(
        repo_root=tmp_path / "repo",
        shared_state_dir=tmp_path / "shared",
        network_state_dir=tmp_path / "network",
        recovery_state_dir=tmp_path / "recovery",
        continuity_state_dir=tmp_path / "continuity",
        output_dir=out,
        config_path=config,
        now=now,
    )
    assert result["handoff_dispatch_count"] == 4
    assert result["authorization"]["authority_minted_by_world"] is False
    doc = json.loads((out / "world_handoffs.json").read_text())
    assert doc["schema"] == HANDOFF_SCHEMA
    assert {row["workflow"] for row in doc["handoffs"] if row["dispatch"]} == {
        "shared-discovery-authority-cycle.yml",
        "meta-network-policy-expansion.yml",
        "senju-external-recovery-cycle.yml",
        "meta-x-production-continuity.yml",
    }
    assert all(row["authority_change_requested"] is False for row in doc["handoffs"])


def test_checkpoint_never_contains_raw_secret_material(tmp_path: Path):
    now = 2_000_000_000
    shared = tmp_path / "shared"
    secret = "SUPER-SECRET-VALUE-DO-NOT-PERSIST"
    _write(
        shared / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "credentialed",
                    "target": "api.example.com",
                    "url": "https://api.example.com/write",
                    "authorization_reference": "owner:api",
                    "capabilities": ["credentialed_action"],
                    "credential_scope": "provider-token-scope",
                    "capability_authorization_profile": "api.example.com",
                    "issued_at": now - 1,
                    "expires_at": now + 1000,
                    "status": "active",
                }
            ],
        },
    )
    config = tmp_path / "world.json"
    _config(config)
    out = tmp_path / "out"
    build_world_trust_root_checkpoint(
        repo_root=tmp_path / "repo",
        shared_state_dir=shared,
        network_state_dir=tmp_path / "network",
        recovery_state_dir=tmp_path / "recovery",
        continuity_state_dir=tmp_path / "continuity",
        output_dir=out,
        config_path=config,
        now=now,
    )
    combined = "\n".join(path.read_text() for path in out.glob("*.json"))
    assert secret not in combined
    assert "provider-token-scope" in combined
