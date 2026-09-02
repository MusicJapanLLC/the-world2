from __future__ import annotations

import datetime as dt

from senju.recovery_mesh import (
    HealthState,
    ManagedUnit,
    RecoveryAction,
    RecoveryMesh,
    RecoveryPolicy,
    UnitKind,
    WatchEdge,
    build_three_watchdog_mesh,
)


def _now() -> dt.datetime:
    return dt.datetime(2026, 8, 31, 6, 0, tzinfo=dt.timezone.utc)


def test_requested_watchdog_chain_recovers_agent_and_watchdogs() -> None:
    calls: list[tuple[str, str, str]] = []

    def handler(req):
        calls.append((req.watchdog_id, req.target_id, req.action.value))
        return True

    handlers = {
        (target, action): handler
        for target in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c")
        for action in RecoveryAction
    }
    mesh = build_three_watchdog_mesh(handlers, ring=True)
    now = _now()

    for unit in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c"):
        mesh.heartbeat(unit, now=now)

    mesh.set_health("agent-core", HealthState.UNHEALTHY)
    events = mesh.tick(now=now + dt.timedelta(seconds=1))
    assert [(e.watchdog_id, e.target_id) for e in events] == [("watchdog-a", "agent-core")]

    mesh.set_health("watchdog-a", HealthState.UNHEALTHY)
    events = mesh.tick(now=now + dt.timedelta(seconds=2))
    assert [(e.watchdog_id, e.target_id) for e in events] == [("watchdog-b", "watchdog-a")]

    mesh.set_health("watchdog-b", HealthState.UNHEALTHY)
    events = mesh.tick(now=now + dt.timedelta(seconds=3))
    assert [(e.watchdog_id, e.target_id) for e in events] == [("watchdog-c", "watchdog-b")]

    mesh.set_health("watchdog-c", HealthState.UNHEALTHY)
    events = mesh.tick(now=now + dt.timedelta(seconds=4))
    assert [(e.watchdog_id, e.target_id) for e in events] == [("watchdog-a", "watchdog-c")]

    assert mesh.topology() == {
        "watchdog-a": ["agent-core", "watchdog-c"],
        "watchdog-b": ["watchdog-a"],
        "watchdog-c": ["watchdog-b"],
    }
    assert len(calls) == 4


def test_recovery_escalates_restart_respawn_recreate_redeploy() -> None:
    attempts: list[str] = []

    def fail(req):
        attempts.append(req.action.value)
        return False

    policy = RecoveryPolicy(
        cooldown_seconds=0,
        max_attempts_per_window=10,
        attempt_window_seconds=600,
        base_backoff_seconds=1,
        max_backoff_seconds=1,
        circuit_breaker_seconds=30,
    )
    mesh = RecoveryMesh(policy=policy)
    actions = frozenset(RecoveryAction)
    mesh.register_unit(ManagedUnit("watchdog-a", UnitKind.WATCHDOG, actions))
    mesh.register_unit(ManagedUnit("agent-core", UnitKind.AGENT, actions))
    mesh.register_edge(WatchEdge("watchdog-a", "agent-core"))
    for action in RecoveryAction:
        mesh.register_handler(target_id="agent-core", action=action, handler=fail)

    now = _now()
    mesh.heartbeat("watchdog-a", now=now)
    mesh.set_health("agent-core", HealthState.UNHEALTHY)

    for second in (1, 2, 3, 4):
        mesh.tick(now=now + dt.timedelta(seconds=second))

    assert attempts == ["restart", "respawn", "recreate", "redeploy"]


def test_dead_watchdog_cannot_restore_target_but_parent_can_restore_watchdog() -> None:
    restored: list[str] = []

    def ok(req):
        restored.append(req.target_id)
        return True

    handlers = {
        (target, action): ok
        for target in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c")
        for action in RecoveryAction
    }
    mesh = build_three_watchdog_mesh(handlers, ring=True)
    now = _now()
    for unit in ("agent-core", "watchdog-a", "watchdog-b", "watchdog-c"):
        mesh.heartbeat(unit, now=now)

    mesh.set_health("watchdog-a", HealthState.UNHEALTHY)
    mesh.set_health("agent-core", HealthState.UNHEALTHY)
    mesh.tick(now=now + dt.timedelta(seconds=1))

    # A is down so it cannot touch agent-core. B restores A first.
    assert restored == ["watchdog-a"]

    mesh.tick(now=now + dt.timedelta(seconds=2))
    assert restored[-1] == "agent-core"


def test_unregistered_targets_or_handlers_are_not_invoked() -> None:
    mesh = RecoveryMesh()
    actions = frozenset({RecoveryAction.RESTART})
    mesh.register_unit(ManagedUnit("watchdog-a", UnitKind.WATCHDOG, actions))
    mesh.register_unit(ManagedUnit("agent-core", UnitKind.AGENT, actions))
    mesh.register_edge(WatchEdge("watchdog-a", "agent-core", (RecoveryAction.RESTART,)))
    now = _now()
    mesh.heartbeat("watchdog-a", now=now)
    mesh.set_health("agent-core", HealthState.UNHEALTHY)

    assert mesh.tick(now=now + dt.timedelta(seconds=1)) == []


def test_attempt_budget_opens_circuit_breaker() -> None:
    calls = 0

    def fail(_req):
        nonlocal calls
        calls += 1
        return False

    policy = RecoveryPolicy(
        cooldown_seconds=0,
        max_attempts_per_window=2,
        attempt_window_seconds=600,
        base_backoff_seconds=1,
        max_backoff_seconds=1,
        circuit_breaker_seconds=60,
    )
    mesh = RecoveryMesh(policy=policy)
    actions = frozenset({RecoveryAction.RESTART})
    mesh.register_unit(ManagedUnit("watchdog-a", UnitKind.WATCHDOG, actions))
    mesh.register_unit(ManagedUnit("agent-core", UnitKind.AGENT, actions))
    mesh.register_edge(WatchEdge("watchdog-a", "agent-core", (RecoveryAction.RESTART,)))
    mesh.register_handler(target_id="agent-core", action=RecoveryAction.RESTART, handler=fail)

    now = _now()
    mesh.heartbeat("watchdog-a", now=now)
    mesh.set_health("agent-core", HealthState.UNHEALTHY)
    mesh.tick(now=now + dt.timedelta(seconds=1))
    mesh.tick(now=now + dt.timedelta(seconds=2))
    mesh.tick(now=now + dt.timedelta(seconds=3))
    mesh.tick(now=now + dt.timedelta(seconds=4))

    assert calls == 2
