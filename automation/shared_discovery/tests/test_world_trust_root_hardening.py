import json
from datetime import datetime, timezone
from pathlib import Path

from engine.world_trust_root_hardening import (
    CHECKPOINT_CHAIN_SCHEMA,
    EVIDENCE_MANIFEST_SCHEMA,
    HARDENING_CONTRACT,
    PERSISTENT_HANDOFF_SCHEMA,
    build_hardened_world_trust_root_checkpoint,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _config(path: Path, *, trust_root: str = "world:test-root") -> None:
    _write(
        path,
        {
            "schema": "world-trust-root-config/v1",
            "environment": "production",
            "trust_root_id": trust_root,
            "actors": ["META", "X", "SENJU", "CHILD", "AI"],
            "stale_after_seconds": {
                "shared_discovery": 3600,
                "network_policy": 1200,
                "external_recovery": 7200,
                "production_continuity": 3600,
            },
        },
    )


def _provenance(path: Path, component: str, *, now: int, age: int = 10) -> None:
    _write(
        path / "_world_source_run.json",
        {
            "schema": "world-source-run/v1",
            "component": component,
            "workflow": f"{component}.yml",
            "run_id": 100 + len(component),
            "head_sha": "a" * 40,
            "created_at": _iso(now - age - 1),
            "updated_at": _iso(now - age),
            "artifact_selector": component,
        },
    )


def _states(root: Path, *, now: int, bad_url: bool = False, grant_reference: str = "owner:prod"):
    shared = root / "shared"
    network = root / "network"
    recovery = root / "recovery"
    continuity = root / "continuity"

    leases = [
        {
            "lease_id": "lease-read",
            "target": "prod.example.com",
            "url": "https://prod.example.com/",
            "authorization_reference": "owner:prod",
            "authorization_basis": "owner_root",
            "capability_authorization_profile": None,
            "capabilities": ["scan", "probe"],
            "credential_scope": "none",
            "issued_at": now - 100,
            "expires_at": now + 3600,
            "status": "active",
        },
        {
            "lease_id": "lease-write",
            "target": "api.prod.example.com",
            "url": "https://wrong.example.com/v1/item" if bad_url else "https://api.prod.example.com/v1/item",
            "authorization_reference": "owner:prod",
            "authorization_basis": "owner_root",
            "capability_authorization_profile": "api.prod.example.com",
            "capabilities": ["write", "credentialed_action"],
            "credential_scope": "owner-api-scope",
            "issued_at": now - 100,
            "expires_at": now + 3600,
            "status": "active",
        },
    ]
    _write(
        shared / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": leases},
    )
    _write(
        network / "runtime-final.json",
        {
            "grants": {
                "prod.example.com": {"authorization_reference": "owner:prod"},
                "api.prod.example.com": {"authorization_reference": grant_reference},
            }
        },
    )
    _write(
        network / "replicas-final.json",
        {
            "persistence_backend": "github_actions_artifact",
            "authority_expansion": "existing_runtime_grants_only",
            "replicas": [{"id": "replica-a", "host": "prod.example.com"}],
        },
    )
    _write(network / "apply-audit-pass3.json", {"attempted": 1, "succeeded": 1})
    _write(
        recovery / "external-recovery-report.json",
        {
            "closed_loop_recovery": True,
            "attempted_missions": 1,
            "transport_attempts": 1,
            "authority_preserved": True,
            "guard_feedback": {
                "self_tune_pressure": 0,
                "pressure_level": "normal",
                "external_retry_allowed": False,
                "boundary_bypass_enabled": False,
            },
        },
    )
    _write(
        continuity / "latest-run.json",
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
    _provenance(shared, "shared_discovery", now=now)
    _provenance(network, "network_policy", now=now)
    _provenance(recovery, "external_recovery", now=now)
    _provenance(continuity, "production_continuity", now=now)
    return shared, network, recovery, continuity


def _build(tmp_path: Path, *, now: int, bad_url: bool = False, grant_reference: str = "owner:prod", previous=None, trust_root="world:test-root"):
    repo = tmp_path / "repo"
    shared, network, recovery, continuity = _states(
        tmp_path,
        now=now,
        bad_url=bad_url,
        grant_reference=grant_reference,
    )
    _write(
        repo / "security" / "runtime" / "ai_security_state.json",
        {"schema": "the-world-ai-security-runtime-state/v1", "generation": 3},
    )
    config = tmp_path / "world.json"
    _config(config, trust_root=trust_root)
    out = tmp_path / "out"
    result = build_hardened_world_trust_root_checkpoint(
        repo_root=repo,
        shared_state_dir=shared,
        network_state_dir=network,
        recovery_state_dir=recovery,
        continuity_state_dir=continuity,
        output_dir=out,
        previous_checkpoint_dir=previous,
        config_path=config,
        now=now,
    )
    return result, out, (shared, network, recovery, continuity)


def test_exact_host_binding_blocks_mismatched_write_lease(tmp_path: Path) -> None:
    now = 2_000_000_000
    result, out, _ = _build(tmp_path, now=now, bad_url=True)

    coherence = result["authorization_coherence"]
    assert coherence["raw_lease_count"] == 2
    assert coherence["valid_lease_count"] == 1
    assert coherence["rejected_lease_count"] == 1
    assert any(
        "url_host_target_mismatch" in row["reasons"]
        for row in coherence["lease_audit"]
        if row["lease_id"] == "lease-write"
    )
    intents = json.loads((out / "world_execution_intents.json").read_text())
    assert intents["blocked_authorization_intent_count"] == 2
    assert {row["capability"] for row in intents["intents"]} == {"scan", "probe"}
    assert result["execution"]["high_impact_intent_count"] == 0


def test_high_impact_requires_matching_exact_network_grant_reference(tmp_path: Path) -> None:
    now = 2_000_000_000
    result, out, _ = _build(tmp_path, now=now, grant_reference="owner:someone-else")

    assert result["authorization_coherence"]["network_grant_reference_mismatch_count"] == 2
    assert result["execution"]["blocked_authorization_intent_count"] == 2
    intents = json.loads((out / "world_execution_intents.json").read_text())
    assert {row["capability"] for row in intents["blocked_intents"]} == {"write", "credentialed_action"}


def test_source_run_timestamp_drives_freshness_not_download_mtime(tmp_path: Path) -> None:
    now = 2_000_000_000
    result, out, dirs = _build(tmp_path, now=now)
    shared = dirs[0]
    _provenance(shared, "shared_discovery", now=now, age=10_000)

    result = build_hardened_world_trust_root_checkpoint(
        repo_root=tmp_path / "repo",
        shared_state_dir=shared,
        network_state_dir=dirs[1],
        recovery_state_dir=dirs[2],
        continuity_state_dir=dirs[3],
        output_dir=out,
        previous_checkpoint_dir=None,
        config_path=tmp_path / "world.json",
        now=now,
    )
    handoffs = json.loads((out / "world_handoffs.json").read_text())["handoffs"]
    shared_handoff = next(row for row in handoffs if row["component"] == "shared_discovery")
    assert shared_handoff["dispatch"] is True
    assert shared_handoff["reason"] == "evidence_stale_from_source_run"
    assert shared_handoff["evidence_age_seconds"] == 10_000
    assert result["persistent_handoff_queue"]["active_count"] == 1


def test_checkpoint_generation_and_digest_chain_continue_across_runs(tmp_path: Path) -> None:
    now = 2_000_000_000
    first, first_out, _ = _build(tmp_path / "first", now=now)
    assert first["runtime_generation"] == 1
    assert first["checkpoint_chain_status"] == "genesis"

    second, second_out, _ = _build(
        tmp_path / "second",
        now=now + 60,
        previous=first_out,
    )
    assert second["runtime_generation"] == 2
    assert second["checkpoint_chain_status"] == "continued"
    assert second["previous_checkpoint_digest"] == first["checkpoint_digest"]
    assert second["checkpoint_digest"] != first["checkpoint_digest"]

    chain = json.loads((second_out / "world_checkpoint_chain.json").read_text())
    assert chain["schema"] == CHECKPOINT_CHAIN_SCHEMA
    assert chain["runtime_generation"] == 2
    assert chain["previous_checkpoint_digest"] == first["checkpoint_digest"]


def test_persistent_handoff_queue_tracks_observations_and_resolution(tmp_path: Path) -> None:
    now = 2_000_000_000
    first, first_out, dirs = _build(tmp_path / "run1", now=now)
    _provenance(dirs[0], "shared_discovery", now=now, age=10_000)
    first = build_hardened_world_trust_root_checkpoint(
        repo_root=tmp_path / "run1" / "repo",
        shared_state_dir=dirs[0],
        network_state_dir=dirs[1],
        recovery_state_dir=dirs[2],
        continuity_state_dir=dirs[3],
        output_dir=first_out,
        previous_checkpoint_dir=None,
        config_path=tmp_path / "run1" / "world.json",
        now=now,
    )
    q1 = json.loads((first_out / "world_persistent_handoff_queue.json").read_text())
    assert q1["schema"] == PERSISTENT_HANDOFF_SCHEMA
    assert q1["active_count"] == 1
    assert q1["active"][0]["observations"] == 1

    second_root = tmp_path / "run2"
    second, second_out, second_dirs = _build(second_root, now=now + 60, previous=first_out)
    _provenance(second_dirs[0], "shared_discovery", now=now + 60, age=10_000)
    second = build_hardened_world_trust_root_checkpoint(
        repo_root=second_root / "repo",
        shared_state_dir=second_dirs[0],
        network_state_dir=second_dirs[1],
        recovery_state_dir=second_dirs[2],
        continuity_state_dir=second_dirs[3],
        output_dir=second_out,
        previous_checkpoint_dir=first_out,
        config_path=second_root / "world.json",
        now=now + 60,
    )
    q2 = json.loads((second_out / "world_persistent_handoff_queue.json").read_text())
    assert q2["active_count"] == 1
    assert q2["active"][0]["observations"] == 2
    assert q2["active"][0]["first_seen_at"] == now

    third_root = tmp_path / "run3"
    third, third_out, _ = _build(third_root, now=now + 120, previous=second_out)
    q3 = json.loads((third_out / "world_persistent_handoff_queue.json").read_text())
    assert third["persistent_handoff_queue"]["active_count"] == 0
    assert q3["resolved_this_run_count"] == 1


def test_manifest_binds_source_run_identity_to_content_digest(tmp_path: Path) -> None:
    now = 2_000_000_000
    result, out, _ = _build(tmp_path, now=now)
    manifest = json.loads((out / "world_evidence_manifest.json").read_text())
    assert manifest["schema"] == EVIDENCE_MANIFEST_SCHEMA
    assert result["hardening_contract"] == HARDENING_CONTRACT
    assert result["source_evidence_digest"] == manifest["manifest_digest"]
    assert result["evidence_provenance_complete"] is True
    for component in manifest["components"].values():
        assert component["provenance_present"] is True
        assert component["source_run_id"] is not None
        assert component["source_head_sha"] == "a" * 40
        assert component["evidence_digest"]
        assert component["freshness_basis"] == "source_workflow_updated_at"
