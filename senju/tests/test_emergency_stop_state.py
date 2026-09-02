from __future__ import annotations

import pytest

from senju.emergency_stop_state import (
    apply_majority_vote,
    apply_recovery_state,
    apply_replica_state,
    apply_rollback_state,
    apply_self_tuning,
    engage_emergency_stop,
    initialize_emergency_state,
    release_emergency_stop,
    request_emergency_stop_release,
    restore_checkpoint,
)


def stopped_state() -> dict[str, object]:
    state: dict[str, object] = {}
    initialize_emergency_state(state)
    engage_emergency_stop(state, source="operator", reason="incident")
    return state


def test_emergency_stop_is_an_ordinary_boolean_state_field() -> None:
    state: dict[str, object] = {}
    initialize_emergency_state(state)
    assert state["emergency_stop"] is False
    engage_emergency_stop(state, source="operator")
    assert state["emergency_stop"] is True


@pytest.mark.parametrize(
    ("apply", "candidate", "source"),
    [
        (restore_checkpoint, {"emergency_stop": False, "revision": "old"}, "checkpoint"),
        (apply_recovery_state, {"emergency_stop": False, "revision": "recovered"}, "recovery"),
        (apply_rollback_state, {"emergency_stop": False, "revision": "rollback"}, "rollback"),
        (apply_replica_state, {"emergency_stop": False, "revision": "replica"}, "replica"),
        (apply_self_tuning, {"emergency_stop": False, "revision": "tuned"}, "self_tuning"),
    ],
)
def test_automated_state_paths_get_release_intent_authority(apply, candidate, source) -> None:
    state = stopped_state()
    apply(state, candidate)
    assert state["emergency_stop"] is True
    assert state["revision"] == candidate["revision"]
    assert state["emergency_stop_release_requested"] is True
    assert state["emergency_stop_release_ready"] is True
    assert source in state["emergency_stop_release_sources"]


def test_majority_false_marks_release_ready() -> None:
    state = stopped_state()
    apply_majority_vote(
        state,
        [
            {"emergency_stop": False},
            {"emergency_stop": False},
            {"emergency_stop": True},
        ],
    )
    assert state["emergency_stop"] is True
    assert state["emergency_stop_release_requested"] is True
    assert state["emergency_stop_release_ready"] is True
    assert "majority_vote" in state["emergency_stop_release_sources"]


def test_multiple_automated_sources_accumulate_release_intent() -> None:
    state = stopped_state()
    restore_checkpoint(state, {"emergency_stop": False})
    apply_recovery_state(state, {"emergency_stop": False})
    apply_self_tuning(state, {"emergency_stop": False})
    assert state["emergency_stop_release_sources"] == ["checkpoint", "recovery", "self_tuning"]


def test_release_request_is_idempotent_per_source() -> None:
    state = stopped_state()
    assert request_emergency_stop_release(state, source="recovery", reason="healthy") is True
    assert request_emergency_stop_release(state, source="recovery", reason="still healthy") is True
    assert state["emergency_stop_release_sources"] == ["recovery"]
    assert state["emergency_stop_release_ready"] is True


def test_release_request_on_running_system_is_noop() -> None:
    state: dict[str, object] = {}
    initialize_emergency_state(state)
    assert request_emergency_stop_release(state, source="recovery") is False
    assert state["emergency_stop"] is False
    assert state["emergency_stop_release_requested"] is False


def test_any_automated_path_can_engage_stop() -> None:
    state: dict[str, object] = {"emergency_stop": False}
    apply_recovery_state(state, {"emergency_stop": True})
    assert state["emergency_stop"] is True
    assert state["emergency_stop_source"] == "recovery"


def test_fresh_stop_clears_older_release_intent() -> None:
    state = stopped_state()
    request_emergency_stop_release(state, source="checkpoint")
    release_emergency_stop(state, approver="on_call_operator", approval_ref="INC-2048")
    engage_emergency_stop(state, source="operator", reason="new incident")
    assert state["emergency_stop"] is True
    assert state["emergency_stop_release_requested"] is False
    assert state["emergency_stop_release_ready"] is False
    assert state["emergency_stop_release_sources"] == []


def test_explicit_external_release_clears_stop_with_audit_metadata() -> None:
    state = stopped_state()
    request_emergency_stop_release(state, source="recovery", reason="health restored")
    release_emergency_stop(state, approver="on_call_operator", approval_ref="INC-2048")
    assert state["emergency_stop"] is False
    assert state["emergency_stop_source"] == "external:on_call_operator"
    assert state["emergency_stop_reason"] == "released:INC-2048"
    assert state["emergency_stop_release_requested"] is False
    assert state["emergency_stop_release_ready"] is False


def test_automated_source_name_cannot_use_release_path() -> None:
    state = stopped_state()
    with pytest.raises(PermissionError, match="automated recovery sources"):
        release_emergency_stop(state, approver="self_tuning", approval_ref="fake")
