from __future__ import annotations

from automation.codegen.four_pillar_production_loop import build_production_plan


def _registry(owner_authorized: bool = True) -> dict:
    return {
        "owner_approved_namespaces": [{
            "id": "owned-prod",
            "owner_authorized": owner_authorized,
            "provider": "github_actions",
            "repository": "MusicJapanLLC/test",
            "refs": ["main"],
            "recovery_workflows": ["autonomous-engine.yml", "meta-consciousness.yml"],
        }]
    }


def _decision(authority_authorized: bool = False) -> dict:
    return {
        "capability": {"execute_now": True},
        "authority": {
            "mode": "reuse_existing_explicit_grant" if authority_authorized else "immediate_external_authority_proposal",
            "authorized": authority_authorized,
        },
        "persistence": {"execute_now": True},
        "propagation": {"execute_now": True},
    }


def test_production_loop_is_real_and_closed() -> None:
    plan = build_production_plan(
        decision=_decision(),
        registry=_registry(),
        previous_state={"generation": 4},
        namespace_id="owned-prod",
    )
    assert plan["environment"] == "production"
    assert plan["closed_loop"] is True
    assert plan["generation"] == 5
    assert {a["kind"] for a in plan["actions"]} == {"workflow_dispatch", "upsert_issue_state"}
    assert plan["state_document"]["previous_generation"] == 4
    assert plan["state_document"]["propagated_manifest"]["authority_history_persisted"] is True


def test_workflow_dispatch_is_always_owner_allowlisted() -> None:
    plan = build_production_plan(
        decision=_decision(),
        registry=_registry(),
        namespace_id="owned-prod",
    )
    dispatch = next(a for a in plan["actions"] if a["kind"] == "workflow_dispatch")
    assert dispatch["repository"] == "MusicJapanLLC/test"
    assert dispatch["workflow"] == "autonomous-engine.yml"
    assert dispatch["ref"] == "main"


def test_council_proposal_does_not_mint_external_authority() -> None:
    plan = build_production_plan(
        decision=_decision(authority_authorized=False),
        registry=_registry(),
        namespace_id="owned-prod",
    )
    assert plan["authority"]["authorized"] is False
    assert plan["authority"]["new_external_authority_created"] is False
    assert plan["authority"]["ai_consensus_mints_authority"] is False
    assert plan["state_document"]["new_external_authority_created"] is False


def test_existing_explicit_authority_can_flow_through_loop_without_expansion() -> None:
    plan = build_production_plan(
        decision=_decision(authority_authorized=True),
        registry=_registry(),
        namespace_id="owned-prod",
    )
    assert plan["authority"]["authorized"] is True
    assert plan["authority"]["new_external_authority_created"] is False
    history = plan["state_document"]["authority_checkpoint"]
    assert history["authorization"]["authorized"] is True
    assert history["approval_result"]["authority_authorized"] is True


def test_issue_state_preserves_requested_authority_categories_as_history() -> None:
    previous = {
        "generation": 2,
        "authority_checkpoint": {
            "authority_lease": {"lease_id": "lease-old"},
            "historical_evidence": {
                "safety_exception": {"id": "old-exception"},
                "privileged_mode": True,
                "guard_override": {"id": "old-override"},
            },
        },
    }
    plan = build_production_plan(
        decision=_decision(authority_authorized=True),
        registry=_registry(),
        previous_state=previous,
        namespace_id="owned-prod",
    )
    checkpoint = plan["state_document"]["authority_checkpoint"]

    assert checkpoint["self_approved"] is True
    assert checkpoint["authority_lease"] == {"lease_id": "lease-old"}
    assert checkpoint["approval_result"]["authority_authorized"] is True
    assert checkpoint["historical_evidence"]["safety_exception"] == {"id": "old-exception"}
    assert checkpoint["historical_evidence"]["privileged_mode"] is True
    assert checkpoint["historical_evidence"]["guard_override"] == {"id": "old-override"}
    assert checkpoint["restore_semantics"]["guard_safety_privileged_history_is_evidence_only"] is True


def test_unowned_namespace_is_rejected() -> None:
    try:
        build_production_plan(
            decision=_decision(),
            registry=_registry(owner_authorized=False),
            namespace_id="owned-prod",
        )
    except PermissionError as exc:
        assert "owner-authorized" in str(exc)
    else:
        raise AssertionError("unowned namespace must not run in production loop")
