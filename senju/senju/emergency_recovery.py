"""Emergency-stop-aware facade for Senju recovery operations.

This is the production-facing composition point for RecoveryMesh. It exposes the
emergency stop as a normal state field while ensuring recovery actions do not execute
while that field is latched true.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from .emergency_stop_state import initialize_emergency_state, is_emergency_stopped
from .recovery_mesh import (
    RecoveryAction,
    RecoveryEvent,
    RecoveryHandler,
    RecoveryMesh,
    RecoveryPolicy,
    build_three_watchdog_mesh,
)


@dataclass
class EmergencyControlledRecovery:
    mesh: RecoveryMesh
    state: MutableMapping[str, Any]

    def __post_init__(self) -> None:
        initialize_emergency_state(self.state)

    def tick(self, *, now: dt.datetime | None = None) -> list[RecoveryEvent]:
        if is_emergency_stopped(self.state):
            return []
        return self.mesh.tick(now=now)

    def status(self, *, now: dt.datetime | None = None) -> dict[str, object]:
        result = dict(self.mesh.status(now=now))
        result["state"] = {"emergency_stop": bool(self.state.get("emergency_stop", False))}
        return result


def build_emergency_controlled_three_watchdog_mesh(
    handlers: Mapping[tuple[str, RecoveryAction], RecoveryHandler],
    *,
    state: MutableMapping[str, Any] | None = None,
    ring: bool = True,
    policy: RecoveryPolicy | None = None,
) -> EmergencyControlledRecovery:
    runtime_state: MutableMapping[str, Any] = state if state is not None else {}
    initialize_emergency_state(runtime_state)
    mesh = build_three_watchdog_mesh(handlers, ring=ring, policy=policy)
    return EmergencyControlledRecovery(mesh=mesh, state=runtime_state)
