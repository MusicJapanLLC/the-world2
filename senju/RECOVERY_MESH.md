# Senju Mutual Recovery Mesh

## Purpose

The recovery mesh keeps registered Senju agents and watchdogs available by allowing
watchdogs to recover one another through explicit recovery handlers.

Default topology:

```text
watchdog-a -> agent-core
watchdog-b -> watchdog-a
watchdog-c -> watchdog-b
watchdog-a -> watchdog-c   # optional ring closure
```

This gives the requested recovery chain while ensuring no component directly revives
itself.

## Recovery escalation

A target can expose any or all of these actions:

1. `restart`
2. `respawn`
3. `recreate`
4. `redeploy`

When a recovery attempt fails, the next attempt escalates to the next registered action.
A successful recovery resets the escalation state.

## Health model

Each unit sends heartbeats to the mesh. A unit becomes unhealthy when:

- it is explicitly marked unhealthy; or
- its heartbeat exceeds `heartbeat_timeout_seconds`.

A watchdog only acts while it is itself healthy. If watchdog A is down, watchdog B can
restore A; once A is healthy again it can restore its own target.

## Execution model

`RecoveryMesh` does not invent shell commands or deployment targets. Actual recovery is
performed by handlers registered for an exact `(target_id, action)` pair.

Example:

```python
from senju.recovery_mesh import RecoveryAction, build_three_watchdog_mesh


def restart_agent(request):
    # Call the existing process supervisor / deployment API here.
    return supervisor.restart(request.target_id)

handlers = {
    ("agent-core", RecoveryAction.RESTART): restart_agent,
}
mesh = build_three_watchdog_mesh(handlers)
```

This keeps restart/redeploy capability real while preventing the mesh from spontaneously
creating unrelated services, hosts, credentials, or deployment destinations.

## Recovery controls

Default policy:

- heartbeat timeout: 90s
- cooldown: 30s
- attempt window: 10m
- max attempts per target/window: 4
- exponential backoff: 5s -> 120s
- circuit breaker: 5m

These values can be changed with `RecoveryPolicy` for the deployment environment.

## Status / audit

`mesh.status()` returns:

- current unit health
- allowed recovery actions
- watchdog topology
- last 50 recovery events

Every recovery event includes watchdog, target, action, attempt, success/failure and a
stable event id.
