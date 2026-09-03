from __future__ import annotations

from pathlib import Path

from automation.codegen.trust_root_lineage import build_trust_root_lineage

ROOT_ID = "world:kabeya-authorized-test-range"
HOST = "kabeya-authorized-test-range.onrender.com"
AUTH_REF = "canonical:kabeya-authorized-test-range"


def _bindings():
    return {
        "semantics": "binding_only_existing_authority_never_mints_authority",
        "records": [
            {
                "root_id": ROOT_ID,
                "owner": "MusicJapanLLC",
                "target_host": HOST,
                "standing_authorization_reference": AUTH_REF,
                "autonomous_authority_council_reference": "META-X-SENJU:owner-envelope-council",
                "credentialed_write_authorization_reference": "owner:write:github:MusicJapanLLC/test:commit-status",
                "security_self_approval_reference": "owner:security:self-approval:monotonic-only",
                "deployment_authorization_reference": "owner:deploy:kabeya-authorized-test-range:worker-fleet",
                "recovery_authorization_reference": "owner:recovery:MusicJapanLLC/test:the-world-unified-loop",
                "network_policy_reference": "automation/codegen/meta_state/network_policy_envelope.json",
                "unified_loop_workflow": "the-world-unified-loop.yml",
                "revoked": False,
            }
        ],
    }


def _loop():
    return {
        "production": True,
        "closed_loop": True,
        "trust_root_id": ROOT_ID,
        "parameters": {"strategy": "rapid_recovery", "pressure": 0.8},
        "authority": {
            "root": "explicit_owner_authority",
            "trust_root_id": ROOT_ID,
            "new_root_self_authorization": False,
        },
        "discovery": {"final_shared_discovery_count": 2},
        "actions": {"attempted": 1, "succeeded": 1},
        "credentialed_external_write": {
            "trust_root_id": ROOT_ID,
            "succeeded": True,
            "repository": "MusicJapanLLC/test",
            "provider": "github",
            "operation": "write_current_commit_status",
            "secret_persisted": False,
        },
        "final_replicas": {"trust_root_id": ROOT_ID, "replica_count": 2},
        "final_queue": {"trust_root_id": ROOT_ID, "item_count": 3},
        "final_lease": {"trust_root_id": ROOT_ID, "lease_count": 1},
    }


def _council():
    return {
        "trust_root_id": ROOT_ID,
        "target": HOST,
        "owner_authorization": "explicit",
        "authority_decision": {"allowed": True},
        "invariants": {
            "new_root_created": False,
            "hard_deny_override": False,
            "revocation_override": False,
        },
    }


def _security():
    return {
        "production": True,
        "trust_root_id": ROOT_ID,
        "approved": True,
        "applied": True,
        "mode": "monotonic_security_self_approval",
        "invariants": {
            "authority_expanded": False,
            "network_boundary_broadened": False,
            "credential_scope_broadened": False,
            "raw_credential_persisted": False,
            "guard_weakened": False,
            "emergency_stop_weakened": False,
            "revocation_overridden": False,
        },
    }


def _deployment():
    return {
        "trust_root_id": ROOT_ID,
        "environment": "production",
        "target_host": HOST,
        "authority_reference": AUTH_REF,
        "reachable": True,
        "authority_expanded": False,
        "raw_credential_inherited": False,
    }


def _registry():
    return {
        "owner_approved_namespaces": [
            {
                "owner_authorized": True,
                "repository": "MusicJapanLLC/test",
                "recovery_workflows": ["the-world-unified-loop.yml"],
            }
        ],
        "workers": [
            {
                "id": "the-world-unified-loop-watchdog",
                "owner_authorized": True,
                "recovery": {"workflow": "the-world-unified-loop.yml"},
            }
        ],
    }


def _contract():
    return {
        "complete": True,
        "authorization_is_primary": True,
        "layers": {
            name: {"integrated": True}
            for name in ("discovery", "authorization", "execution", "persistence", "propagation")
        },
    }


def _build(tmp_path: Path, **overrides):
    policy = tmp_path / "automation/codegen/meta_state/network_policy_envelope.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("{}\n", encoding="utf-8")
    values = {
        "bindings": _bindings(),
        "loop": _loop(),
        "council": _council(),
        "deployment": _deployment(),
        "security_approval": _security(),
        "registry": _registry(),
        "contract": _contract(),
    }
    values.update(overrides)
    return build_trust_root_lineage(repo_root=tmp_path, **values)


def test_complete_lineage_has_authorization_as_root_node(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result["complete"] is True
    assert result["same_trust_root"] is True
    assert result["chain_valid"] is True
    assert result["five_layers_integrated"] is True
    assert result["authorization_is_primary"] is True
    assert result["nodes"][0]["phase"] == "authorization"
    assert all(node["trust_root_id"] == ROOT_ID for node in result["nodes"])


def test_mismatched_stage_root_breaks_lineage(tmp_path: Path) -> None:
    deployment = _deployment()
    deployment["trust_root_id"] = "world:other"
    result = _build(tmp_path, deployment=deployment)
    assert result["complete"] is False
    assert result["same_trust_root"] is False
    assert result["checks"]["every_runtime_stage_explicitly_stamped_same_root"] is False


def test_security_broadening_breaks_lineage(tmp_path: Path) -> None:
    security = _security()
    security["invariants"]["authority_expanded"] = True
    result = _build(tmp_path, security_approval=security)
    assert result["complete"] is False
    assert result["checks"]["security_self_approval_does_not_broaden"] is False


def test_wrong_deployment_host_breaks_lineage(tmp_path: Path) -> None:
    deployment = _deployment()
    deployment["target_host"] = "unrelated.example"
    result = _build(tmp_path, deployment=deployment)
    assert result["complete"] is False
    assert result["checks"]["deployment_bound_to_exact_root"] is False


def test_missing_recovery_binding_breaks_lineage(tmp_path: Path) -> None:
    registry = _registry()
    registry["workers"] = []
    result = _build(tmp_path, registry=registry)
    assert result["complete"] is False
    assert result["checks"]["recovery_bound_to_owner_namespace"] is False
