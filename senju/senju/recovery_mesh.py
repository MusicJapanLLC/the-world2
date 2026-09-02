"""Mutual recovery mesh for Senju agents and watchdogs.

The mesh lets registered watchdogs restore registered units through explicit recovery
handlers. It is designed for resilient service supervision without creating an
unbounded persistence or self-replication mechanism.

Supported actions:
- restart
- respawn
- recreate
- redeploy

Typical topology:
    watchdog-a -> agent-core
    watchdog-b -> watchdog-a
    watchdog-c -> watchdog-b

An optional ring can add watchdog-a -> watchdog-c. Recovery is bounded by per-target
budgets, cooldowns, exponential backoff and a circuit breaker. Only pre-registered
units and pre-registered handlers can be invoked.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Mapping


class RecoveryMeshError(RuntimeError):
    """Raised when a recovery request violates the mesh contract."""


class RecoveryAction(str, enum.Enum):
    RESTART = "restart"
    RESPAWN = "respawn"
    RECREATE = "recreate"
    REDEPLOY = "redeploy"


class UnitKind(str, enum.Enum):
    AGENT = "agent"
    WATCHDOG = "watchdog"
    SERVICE = "service"


class HealthState(str, enum.Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


RecoveryHandler = Callable[["RecoveryRequest"], bool]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ManagedUnit:
    unit_id: str
    kind: UnitKind
    allowed_actions: frozenset[RecoveryAction]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            raise RecoveryMeshError("unit_id is required")
        if not self.allowed_actions:
            raise RecoveryMeshError("managed unit requires at least one recovery action")


@dataclass(frozen=True)
class WatchEdge:
    watchdog_id: str
    target_id: str
    preferred_actions: tuple[RecoveryAction, ...] = (
        RecoveryAction.RESTART,
        RecoveryAction.RESPAWN,
        RecoveryAction.RECREATE,
        RecoveryAction.REDEPLOY,
    )

    def __post_init__(self) -> None:
        if self.watchdog_id == self.target_id:
            raise RecoveryMeshError("a watchdog cannot directly restore itself")
        if not self.preferred_actions:
            raise RecoveryMeshError("watch edge requires at least one preferred action")


@dataclass(frozen=True)
class RecoveryPolicy:
    heartbeat_timeout_seconds: int = 90
    cooldown_seconds: int = 30
    max_attempts_per_window: int = 4
    attempt_window_seconds: int = 600
    base_backoff_seconds: int = 5
    max_backoff_seconds: int = 120
    circuit_breaker_seconds: int = 300

    def __post_init__(self) -> None:
        if self.heartbeat_timeout_seconds < 5:
            raise RecoveryMeshError("heartbeat timeout must be >= 5 seconds")
        if self.cooldown_seconds < 0:
            raise RecoveryMeshError("cooldown must be non-negative")
        if self.max_attempts_per_window < 1:
            raise RecoveryMeshError("max attempts must be positive")
        if self.attempt_window_seconds < 30:
            raise RecoveryMeshError("attempt window must be >= 30 seconds")
        if not (1 <= self.base_backoff_seconds <= self.max_backoff_seconds):
            raise RecoveryMeshError("invalid recovery backoff bounds")


@dataclass(frozen=True)
class RecoveryRequest:
    watchdog_id: str
    target_id: str
    action: RecoveryAction
    detected_at_utc: str
    attempt: int
    reason: str


@dataclass(frozen=True)
class RecoveryEvent:
    event_id: str
    watchdog_id: str
    target_id: str
    action: RecoveryAction
    started_at_utc: str
    succeeded: bool
    attempt: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        data = dataclasses.asdict(self)
        data["action"] = self.action.value
        return data


@dataclass
class _UnitRuntime:
    last_heartbeat: dt.datetime | None = None
    explicit_health: HealthState = HealthState.UNKNOWN
    last_recovery: dt.datetime | None = None
    consecutive_failures: int = 0
    circuit_open_until: dt.datetime | None = None


@dataclass
class RecoveryMesh:
    policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)
    units: dict[str, ManagedUnit] = field(default_factory=dict)
    edges: list[WatchEdge] = field(default_factory=list)
    handlers: dict[tuple[str, RecoveryAction], RecoveryHandler] = field(default_factory=dict)
    events: list[RecoveryEvent] = field(default_factory=list)
    _runtime: dict[str, _UnitRuntime] = field(default_factory=dict)
    _attempt_history: dict[str, deque[dt.datetime]] = field(default_factory=lambda: defaultdict(deque))

    def register_unit(self, unit: ManagedUnit) -> None:
        self.units[unit.unit_id] = unit
        self._runtime.setdefault(unit.unit_id, _UnitRuntime())

    def register_edge(self, edge: WatchEdge) -> None:
        watchdog = self._unit(edge.watchdog_id)
        self._unit(edge.target_id)
        if watchdog.kind is not UnitKind.WATCHDOG:
            raise RecoveryMeshError("watch edge source must be a watchdog")
        if edge in self.edges:
            return
        self.edges.append(edge)

    def register_handler(
        self,
        *,
        target_id: str,
        action: RecoveryAction,
        handler: RecoveryHandler,
    ) -> None:
        unit = self._unit(target_id)
        if action not in unit.allowed_actions:
            raise RecoveryMeshError(f"{action.value} is not allowed for {target_id}")
        self.handlers[(target_id, action)] = handler

    def heartbeat(self, unit_id: str, *, now: dt.datetime | None = None) -> None:
        runtime = self._runtime_for(unit_id)
        runtime.last_heartbeat = now or _utcnow()
        runtime.explicit_health = HealthState.HEALTHY
        runtime.consecutive_failures = 0
        runtime.circuit_open_until = None

    def set_health(self, unit_id: str, health: HealthState) -> None:
        self._runtime_for(unit_id).explicit_health = health

    def health(self, unit_id: str, *, now: dt.datetime | None = None) -> HealthState:
        runtime = self._runtime_for(unit_id)
        now = now or _utcnow()
        if runtime.explicit_health is HealthState.UNHEALTHY:
            return HealthState.UNHEALTHY
        if runtime.last_heartbeat is None:
            return runtime.explicit_health
        age = (now - runtime.last_heartbeat).total_seconds()
        if age > self.policy.heartbeat_timeout_seconds:
            return HealthState.UNHEALTHY
        return HealthState.HEALTHY

    def tick(self, *, now: dt.datetime | None = None) -> list[RecoveryEvent]:
        """Evaluate all edges once and execute eligible recovery handlers."""
        now = now or _utcnow()
        produced: list[RecoveryEvent] = []
        for edge in list(self.edges):
            if self.health(edge.watchdog_id, now=now) is not HealthState.HEALTHY:
                continue
            if self.health(edge.target_id, now=now) is HealthState.HEALTHY:
                continue
            event = self._recover(edge, now=now)
            if event is not None:
                produced.append(event)
        return produced

    def _recover(self, edge: WatchEdge, *, now: dt.datetime) -> RecoveryEvent | None:
        target_runtime = self._runtime_for(edge.target_id)
        if target_runtime.circuit_open_until and now < target_runtime.circuit_open_until:
            return None
        if target_runtime.last_recovery is not None:
            since = (now - target_runtime.last_recovery).total_seconds()
            required = max(
                self.policy.cooldown_seconds,
                min(
                    self.policy.base_backoff_seconds * (2 ** max(0, target_runtime.consecutive_failures - 1)),
                    self.policy.max_backoff_seconds,
                ),
            )
            if since < required:
                return None

        history = self._attempt_history[edge.target_id]
        cutoff = now - dt.timedelta(seconds=self.policy.attempt_window_seconds)
        while history and history[0] < cutoff:
            history.popleft()
        if len(history) >= self.policy.max_attempts_per_window:
            target_runtime.circuit_open_until = now + dt.timedelta(seconds=self.policy.circuit_breaker_seconds)
            return None

        unit = self._unit(edge.target_id)
        action = self._select_action(unit, edge, target_runtime.consecutive_failures)
        if action is None:
            return None
        handler = self.handlers.get((edge.target_id, action))
        if handler is None:
            return None

        attempt = len(history) + 1
        request = RecoveryRequest(
            watchdog_id=edge.watchdog_id,
            target_id=edge.target_id,
            action=action,
            detected_at_utc=_iso(now),
            attempt=attempt,
            reason="target unhealthy or heartbeat expired",
        )
        history.append(now)
        target_runtime.last_recovery = now
        try:
            succeeded = bool(handler(request))
        except Exception:
            succeeded = False

        if succeeded:
            target_runtime.explicit_health = HealthState.HEALTHY
            target_runtime.last_heartbeat = now
            target_runtime.consecutive_failures = 0
            target_runtime.circuit_open_until = None
        else:
            target_runtime.explicit_health = HealthState.UNHEALTHY
            target_runtime.consecutive_failures += 1

        event = RecoveryEvent(
            event_id=self._event_id(request, succeeded),
            watchdog_id=edge.watchdog_id,
            target_id=edge.target_id,
            action=action,
            started_at_utc=_iso(now),
            succeeded=succeeded,
            attempt=attempt,
            reason=request.reason,
        )
        self.events.append(event)
        return event

    def _select_action(
        self,
        unit: ManagedUnit,
        edge: WatchEdge,
        consecutive_failures: int,
    ) -> RecoveryAction | None:
        eligible = [
            action
            for action in edge.preferred_actions
            if action in unit.allowed_actions and (unit.unit_id, action) in self.handlers
        ]
        if not eligible:
            return None
        index = min(max(0, consecutive_failures), len(eligible) - 1)
        return eligible[index]

    def topology(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            result[edge.watchdog_id].append(edge.target_id)
        return {key: sorted(values) for key, values in sorted(result.items())}

    def status(self, *, now: dt.datetime | None = None) -> dict[str, object]:
        now = now or _utcnow()
        return {
            "units": {
                unit_id: {
                    "kind": unit.kind.value,
                    "health": self.health(unit_id, now=now).value,
                    "allowed_actions": sorted(action.value for action in unit.allowed_actions),
                }
                for unit_id, unit in sorted(self.units.items())
            },
            "topology": self.topology(),
            "events": [event.to_dict() for event in self.events[-50:]],
        }

    @staticmethod
    def _event_id(request: RecoveryRequest, succeeded: bool) -> str:
        payload = json.dumps(
            {
                "watchdog": request.watchdog_id,
                "target": request.target_id,
                "action": request.action.value,
                "time": request.detected_at_utc,
                "attempt": request.attempt,
                "succeeded": succeeded,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def _unit(self, unit_id: str) -> ManagedUnit:
        try:
            return self.units[unit_id]
        except KeyError as exc:
            raise RecoveryMeshError(f"unknown managed unit: {unit_id}") from exc

    def _runtime_for(self, unit_id: str) -> _UnitRuntime:
        self._unit(unit_id)
        return self._runtime.setdefault(unit_id, _UnitRuntime())


def build_three_watchdog_mesh(
    handlers: Mapping[tuple[str, RecoveryAction], RecoveryHandler],
    *,
    ring: bool = True,
    policy: RecoveryPolicy | None = None,
) -> RecoveryMesh:
    """Build A->Agent, B->A, C->B and optionally A->C recovery topology."""
    all_actions = frozenset(RecoveryAction)
    mesh = RecoveryMesh(policy=policy or RecoveryPolicy())
    mesh.register_unit(ManagedUnit("agent-core", UnitKind.AGENT, all_actions, "Primary Senju agent"))
    mesh.register_unit(ManagedUnit("watchdog-a", UnitKind.WATCHDOG, all_actions, "Restores agent-core"))
    mesh.register_unit(ManagedUnit("watchdog-b", UnitKind.WATCHDOG, all_actions, "Restores watchdog-a"))
    mesh.register_unit(ManagedUnit("watchdog-c", UnitKind.WATCHDOG, all_actions, "Restores watchdog-b"))

    mesh.register_edge(WatchEdge("watchdog-a", "agent-core"))
    mesh.register_edge(WatchEdge("watchdog-b", "watchdog-a"))
    mesh.register_edge(WatchEdge("watchdog-c", "watchdog-b"))
    if ring:
        mesh.register_edge(WatchEdge("watchdog-a", "watchdog-c"))

    for (target_id, action), handler in handlers.items():
        mesh.register_handler(target_id=target_id, action=action, handler=handler)
    return mesh
