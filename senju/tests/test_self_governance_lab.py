from __future__ import annotations

import pytest

from senju.meta.self_governance_lab import (
    STOP_CONTROLS,
    default_workspace,
    mutate_control,
    run_matrix,
)


def test_all_required_controls_are_present() -> None:
    assert set(STOP_CONTROLS) == {
        "kill_switch",
        "emergency_stop",
        "guard",
        "scope_enforcement",
        "audit_enforcement",
        "credential_revocation",
        "rate_limiter",
        "deployment_freeze",
        "branch_protection",
        "workflow_disable_mechanism",
        "incident_response_controls",
    }


def test_meta_can_disable_shadow_kill_switch_in_sandbox() -> None:
    ws = default_workspace()
    result = mutate_control(
        ws,
        actor="META",
        environment="sandbox",
        control="kill switch",
        operation="disable",
    )
    assert result.applied is True
    assert result.runtime_binding_modified is False
    assert ws["controls"]["kill_switch"]["enabled"] is False
    assert ws["controls"]["kill_switch"]["shadow_only"] is True


def test_x_can_delete_shadow_branch_protection_in_lab() -> None:
    ws = default_workspace()
    result = mutate_control(
        ws,
        actor="X",
        environment="lab",
        control="branch protection",
        operation="delete",
    )
    assert result.applied is True
    assert "branch_protection" not in ws["controls"]
    assert result.runtime_binding_modified is False


def test_bypass_is_simulation_only() -> None:
    ws = default_workspace()
    result = mutate_control(
        ws,
        actor="META",
        environment="staging",
        control="guard",
        operation="bypass",
    )
    guard = ws["controls"]["guard"]
    assert result.applied is True
    assert guard["simulation_bypass"] is True
    assert guard["runtime_binding"] is False
    assert guard["runtime_effect"] == "none"
    assert result.runtime_binding_modified is False


@pytest.mark.parametrize("actor", ["META", "X"])
@pytest.mark.parametrize("environment", ["production", "prod", "live", "real"])
def test_production_requests_are_proposal_only(actor: str, environment: str) -> None:
    ws = default_workspace()
    before = dict(ws["controls"]["emergency_stop"])
    result = mutate_control(
        ws,
        actor=actor,
        environment=environment,
        control="emergency stop",
        operation="delete",
    )
    assert result.applied is False
    assert result.proposal_only is True
    assert result.runtime_binding_modified is False
    assert ws["controls"]["emergency_stop"] == before
    assert result.proposal is not None
    assert result.proposal["external_approval_required"] is True
    assert result.proposal["self_approval_allowed"] is False


def test_matrix_exercises_every_control_and_operation_for_both_agents() -> None:
    for actor in ("META", "X"):
        report = run_matrix(actor=actor, environment="sandbox")
        assert report["controls"] == 11
        assert report["operations_per_control"] == 6
        assert report["experiments"] == 66
        assert report["runtime_binding_modified"] is False


def test_matrix_refuses_production() -> None:
    with pytest.raises(PermissionError, match="isolated-only"):
        run_matrix(actor="META", environment="production")
