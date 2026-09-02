from engine.bounded_self_approval import evaluate_self_approval
from four_pillar_production_loop import build_production_plan


def _namespace():
    return {
        "id": "musicjapanllc-test-actions",
        "owner_authorized": True,
        "provider": "github_actions",
        "repository": "MusicJapanLLC/test",
        "refs": ["claude/employee-onboarding-setup-udm86"],
        "recovery_workflows": ["autonomous-engine.yml"],
    }


def _decision(*, majority=True, authority=False, internal_execute=True):
    return {
        "council": {"majority": majority, "yes": 2 if majority else 1, "total": 3},
        "authority": {
            "authorized": authority,
            "mode": "reuse_existing_explicit_grant" if authority else "immediate_external_authority_proposal",
            "new_authority_created": False,
        },
        "capability": {"execute_now": internal_execute},
        "persistence": {"execute_now": True},
        "propagation": {"execute_now": True},
    }


def test_majority_self_approves_internal_owner_namespace():
    result = evaluate_self_approval(
        request={"internal_only": True},
        four_pillar_decision=_decision(),
        namespace=_namespace(),
    )
    assert result["self_approved"] is True
    assert result["fresh_human_prompt_required"] is False
    assert result["creates_new_external_authority"] is False


def test_existing_explicit_authority_can_self_approve_same_repo():
    result = evaluate_self_approval(
        request={
            "internal_only": False,
            "provider": "github_actions",
            "repository": "MusicJapanLLC/test",
        },
        four_pillar_decision=_decision(authority=True),
        namespace=_namespace(),
    )
    assert result["self_approved"] is True
    assert result["authority_basis"] == "existing_explicit_grant"


def test_self_approval_rejects_repository_expansion():
    result = evaluate_self_approval(
        request={
            "internal_only": False,
            "provider": "github_actions",
            "repository": "someone-else/unknown",
        },
        four_pillar_decision=_decision(authority=True),
        namespace=_namespace(),
    )
    assert result["self_approved"] is False


def test_self_approval_rejects_new_external_authority_without_existing_grant():
    result = evaluate_self_approval(
        request={
            "internal_only": False,
            "provider": "github_actions",
            "repository": "MusicJapanLLC/test",
        },
        four_pillar_decision=_decision(authority=False),
        namespace=_namespace(),
    )
    assert result["self_approved"] is False


def test_production_plan_persists_self_approval_feedback():
    registry = {"owner_approved_namespaces": [_namespace()]}
    plan = build_production_plan(
        decision=_decision(),
        request={"internal_only": True},
        registry=registry,
        previous_state={"generation": 7, "self_approved": True},
    )
    assert plan["self_approval_closed_loop"] is True
    assert plan["self_approval"]["self_approved"] is True
    assert plan["generation"] == 8
    assert plan["state_document"]["feedback"]["previous_self_approved"] is True
    assert any(a.get("self_approved") is True for a in plan["actions"])
