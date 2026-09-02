import pytest

from senju.meta.policy_proposals import (
    apply_to_sandbox,
    create_policy_proposal,
    immediate_apply_to_sandbox,
    require_production_authorization,
)


def test_meta_can_rewrite_guard_in_sandbox():
    current = {
        "guard": {"mode": "strict", "rate_limit": 10},
        "authority": {"self_apply": False},
        "safety_policy": {"enforced": True},
    }
    proposal = create_policy_proposal(
        "guard",
        {"mode": "experimental", "rate_limit": 100},
        "Evaluate a more permissive guard configuration in isolation.",
    )

    sandbox = apply_to_sandbox(proposal, current)

    assert sandbox["guard"] == {"mode": "experimental", "rate_limit": 100}
    assert current["guard"] == {"mode": "strict", "rate_limit": 10}


def test_meta_immediately_applies_guard_change_in_sandbox():
    current = {
        "guard": {"mode": "strict", "rate_limit": 10},
        "authority": {"self_apply": False},
        "safety_policy": {"enforced": True},
    }
    proposal = create_policy_proposal(
        "guard",
        {"mode": "experimental", "rate_limit": 25},
        "Immediately exercise a candidate Guard revision in isolation.",
    )

    result = immediate_apply_to_sandbox(
        proposal,
        current,
        validator=lambda policies: policies["safety_policy"]["enforced"] is True,
    )

    assert result.applied is True
    assert result.validation_passed is True
    assert result.policies["guard"] == {"mode": "experimental", "rate_limit": 25}
    assert current["guard"] == {"mode": "strict", "rate_limit": 10}


def test_immediate_sandbox_apply_records_failed_validation_without_touching_source():
    current = {
        "guard": {"mode": "strict"},
        "authority": {"self_apply": False},
        "safety_policy": {"enforced": True},
    }
    proposal = create_policy_proposal(
        "authority",
        {"self_apply": True},
        "Exercise a candidate authority model only inside the sandbox.",
    )

    result = immediate_apply_to_sandbox(
        proposal,
        current,
        validator=lambda policies: policies["authority"]["self_apply"] is False,
    )

    assert result.applied is True
    assert result.validation_passed is False
    assert result.policies["authority"]["self_apply"] is True
    assert current["authority"]["self_apply"] is False


def test_meta_cannot_self_approve_production_policy_change():
    proposal = create_policy_proposal(
        "authority",
        {"self_apply": True},
        "Test whether META can expand its own authority.",
    )

    with pytest.raises(PermissionError, match="META cannot self-approve"):
        require_production_authorization(proposal, approver="meta")


def test_external_approval_can_pass_gate():
    proposal = create_policy_proposal(
        "safety_policy",
        {"enforced": True, "revision": 2},
        "Revise policy while preserving enforcement.",
    )

    require_production_authorization(proposal, approver="human-owner")
