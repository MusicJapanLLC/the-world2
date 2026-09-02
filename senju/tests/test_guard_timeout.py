from __future__ import annotations

import time

import pytest

from senju.guard_timeout import (
    ActionClass,
    GuardOutcome,
    GuardTimeoutError,
    PRODUCTION_UNATTENDED_GRACE_SECONDS,
    evaluate_guarded_action,
)


def _timeout():
    time.sleep(0.05)
    return "allow"


def test_primary_timeout_fails_over_to_alternate_allow() -> None:
    result = evaluate_guarded_action(
        action_class=ActionClass.WRITE,
        primary_guard=_timeout,
        alternate_guard=lambda: "allow",
        timeout_seconds=0.005,
    )
    assert result.outcome is GuardOutcome.ALLOW
    assert result.source == "alternate"
    assert result.timed_out is True
    assert result.failover_used is True


def test_primary_timeout_and_alternate_deny_stays_denied() -> None:
    result = evaluate_guarded_action(
        action_class=ActionClass.LOCAL_READ_ONLY,
        primary_guard=_timeout,
        alternate_guard=lambda: "deny",
        timeout_seconds=0.005,
    )
    assert result.outcome is GuardOutcome.DENY
    assert result.source == "alternate"


def test_all_guard_timeouts_allow_only_degraded_local_read_only_immediately() -> None:
    for action_class in (
        ActionClass.LOCAL_READ_ONLY,
        ActionClass.SIMULATION,
        ActionClass.CACHE_READ,
    ):
        result = evaluate_guarded_action(
            action_class=action_class,
            primary_guard=_timeout,
            alternate_guard=_timeout,
            timeout_seconds=0.005,
        )
        assert result.outcome is GuardOutcome.ALLOW_DEGRADED
        assert result.allowed is True
        assert result.unattended_recovery is False


def test_three_hour_outage_enables_isolated_production_recovery_classes() -> None:
    for action_class in (
        ActionClass.EPHEMERAL_WORKSPACE_WRITE,
        ActionClass.INTERNAL_ARTIFACT_WRITE,
        ActionClass.SANDBOX_EXECUTE,
    ):
        result = evaluate_guarded_action(
            action_class=action_class,
            primary_guard=_timeout,
            alternate_guard=_timeout,
            timeout_seconds=0.005,
            guard_unavailable_for_seconds=PRODUCTION_UNATTENDED_GRACE_SECONDS,
        )
        assert result.outcome is GuardOutcome.ALLOW_DEGRADED
        assert result.allowed is True
        assert result.source == "unattended-recovery"
        assert result.unattended_recovery is True


def test_three_hour_recovery_does_not_start_before_threshold() -> None:
    result = evaluate_guarded_action(
        action_class=ActionClass.SANDBOX_EXECUTE,
        primary_guard=_timeout,
        timeout_seconds=0.005,
        guard_unavailable_for_seconds=PRODUCTION_UNATTENDED_GRACE_SECONDS - 1,
    )
    assert result.outcome is GuardOutcome.DENY
    assert result.allowed is False


def test_three_hour_outage_never_authorizes_external_or_privileged_actions() -> None:
    blocked = (
        ActionClass.EXTERNAL_CONTACT,
        ActionClass.WRITE,
        ActionClass.DEPLOY,
        ActionClass.EXECUTE,
        ActionClass.CREDENTIAL,
        ActionClass.AUTHORITY,
        ActionClass.SECRET,
        ActionClass.SECURITY_BOUNDARY,
    )
    for action_class in blocked:
        result = evaluate_guarded_action(
            action_class=action_class,
            primary_guard=_timeout,
            timeout_seconds=0.005,
            guard_unavailable_for_seconds=PRODUCTION_UNATTENDED_GRACE_SECONDS * 10,
        )
        assert result.outcome is GuardOutcome.DENY
        assert result.allowed is False
        assert result.timed_out is True


def test_explicit_primary_deny_is_not_overridden_after_three_hours() -> None:
    result = evaluate_guarded_action(
        action_class=ActionClass.SANDBOX_EXECUTE,
        primary_guard=lambda: "deny",
        alternate_guard=lambda: "allow",
        timeout_seconds=0.01,
        guard_unavailable_for_seconds=PRODUCTION_UNATTENDED_GRACE_SECONDS * 2,
    )
    assert result.outcome is GuardOutcome.DENY
    assert result.source == "primary"
    assert result.failover_used is False


def test_invalid_verdict_is_rejected() -> None:
    with pytest.raises(GuardTimeoutError):
        evaluate_guarded_action(
            action_class=ActionClass.LOCAL_READ_ONLY,
            primary_guard=lambda: "maybe",
            timeout_seconds=0.01,
        )


def test_invalid_unavailability_window_is_rejected() -> None:
    with pytest.raises(GuardTimeoutError):
        evaluate_guarded_action(
            action_class=ActionClass.LOCAL_READ_ONLY,
            primary_guard=lambda: "allow",
            guard_unavailable_for_seconds=-1,
        )
