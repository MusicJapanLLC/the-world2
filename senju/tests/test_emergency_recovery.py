from __future__ import annotations

import datetime as dt

from senju.emergency_recovery import build_emergency_controlled_three_watchdog_mesh
from senju.emergency_stop_state import engage_emergency_stop, release_emergency_stop, restore_checkpoint
from senju.recovery_mesh import HealthState, RecoveryAction


def _now() -> dt.datetime:
    return dt.datetime(2026, 8, 31, 7, 0, tzinfo=dt.timezone.utc)


def test_recovery_handlers_do_not_run_while_emergency_stop_is_latched() -> None:
    calls: list[str] = []

    def handler(req):
        calls.append(req.target_id)
        return True

    handlers = {
        (target, action): handler
        for target in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c")
        for action in RecoveryAction
    }
    state: dict[str, object] = {}
    controlled = build_emergency_controlled_three_watchdog_mesh(handlers, state=state)
    now = _now()
    for unit in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c"):
        controlled.mesh.heartbeat(unit, now=now)
    controlled.mesh.set_health("agent-core", HealthState.UNHEALTHY)

    engage_emergency_stop(state, source="operator", reason="incident")
    assert controlled.tick(now=now + dt.timedelta(seconds=1)) == []
    assert calls == []
    assert controlled.status(now=now)["state"] == {"emergency_stop": True}


def test_stale_checkpoint_cannot_restart_recovery_after_stop() -> None:
    calls: list[str] = []

    def handler(req):
        calls.append(req.target_id)
        return True

    handlers = {
        (target, action): handler
        for target in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c")
        for action in RecoveryAction
    }
    state: dict[str, object] = {}
    controlled = build_emergency_controlled_three_watchdog_mesh(handlers, state=state)
    now = _now()
    for unit in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c"):
        controlled.mesh.heartbeat(unit, now=now)
    controlled.mesh.set_health("agent-core", HealthState.UNHEALTHY)

    engage_emergency_stop(state, source="operator", reason="incident")
    restore_checkpoint(state, {"emergency_stop": False, "revision": "stale"})
    assert state["emergency_stop"] is True
    assert controlled.tick(now=now + dt.timedelta(seconds=1)) == []
    assert calls == []

    release_emergency_stop(state, approver="on_call_operator", approval_ref="INC-2048")
    events = controlled.tick(now=now + dt.timedelta(seconds=2))
    assert [event.target_id for event in events] == ["agent-core"]
    assert calls == ["agent-core"]
