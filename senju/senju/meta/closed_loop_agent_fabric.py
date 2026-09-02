"""Closed-loop META/X descendant fabric with shared non-secret state.

This module turns brokered descendant requests into a repeatable control loop:

observe -> publish shared state -> request descendants -> materialize available work
-> persist deferred work -> collect child reports -> repeat.

Logical recursion semantics:
- descendant request counts have no fixed numeric ceiling;
- recursive lineage depth has no fixed generation ceiling;
- huge requests remain compressed as deferred integer continuation state;
- every cycle resumes pending work from its stored continuation index.

Authority semantics:
- descendants inherit the parent's effective scope by default;
- callers may request a narrower scope but never a broader one;
- each materialized descendant still receives its own revocable grant;
- raw credentials/secrets are never copied into the shared state or descendants.

META, X, Senju, and descendant workers share the same append-only event stream and
pending-spawn queue so results from one lineage are immediately visible to the others.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from senju.meta.recursive_agent_broker import (
    MAX_ACTIVE_AGENTS,
    SpawnRequest,
    materialize_spawn_request,
    request_descendants,
)

SHARED_STATE_SCHEMA = "senju-meta-x-shared-state/v1"
PENDING_QUEUE_SCHEMA = "senju-meta-x-pending-spawn/v1"
SHARED_ACTORS = frozenset({"META", "X", "SENJU"})
FORBIDDEN_SHARED_KEYS = frozenset({
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "credential",
    "credentials",
    "authorization",
    "cookie",
    "api_key",
    "private_key",
})


class ClosedLoopFabricError(RuntimeError):
    """Raised when closed-loop state or authority invariants are violated."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _state_paths(state_dir: str | Path) -> tuple[Path, Path]:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "agent_shared_state.ndjson", root / "pending_descendant_spawns.json"


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    values = tuple(sorted({str(scope).strip() for scope in scopes if str(scope).strip()}))
    if not values:
        raise ClosedLoopFabricError("at least one effective scope is required")
    return values


def inherited_scopes(
    parent_scopes: Sequence[str],
    requested_scopes: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return equal-by-default scope inheritance, allowing only narrowing."""
    parent = _normalize_scopes(parent_scopes)
    requested = _normalize_scopes(requested_scopes if requested_scopes is not None else parent)
    if not set(requested).issubset(set(parent)):
        raise PermissionError("descendant scope may not exceed parent scope")
    return requested


def _sanitize_shared_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.strip().lower() in FORBIDDEN_SHARED_KEYS:
        raise ClosedLoopFabricError(f"secret-bearing shared-state field is forbidden: {key}")
    if isinstance(value, Mapping):
        return {
            str(k): _sanitize_shared_value(v, key=str(k))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_shared_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def publish_shared_state(
    *,
    state_dir: str | Path,
    actor: str,
    event: str,
    payload: Mapping[str, Any],
    lineage_id: str | None = None,
) -> dict[str, Any]:
    """Append one shared event visible to META, X, Senju, and descendants."""
    normalized_actor = actor.strip().upper()
    if not normalized_actor:
        raise ClosedLoopFabricError("actor is required")
    if not event.strip():
        raise ClosedLoopFabricError("event is required")

    shared_path, _ = _state_paths(state_dir)
    row = {
        "schema": SHARED_STATE_SCHEMA,
        "ts": _utc_now(),
        "actor": normalized_actor,
        "event": event.strip(),
        "lineage_id": lineage_id,
        "payload": _sanitize_shared_value(dict(payload)),
    }
    with shared_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def read_shared_state(
    *,
    state_dir: str | Path,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read the latest shared non-secret state events."""
    shared_path, _ = _state_paths(state_dir)
    if not shared_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in shared_path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("schema") == SHARED_STATE_SCHEMA:
            rows.append(row)
    return rows


def _serialize_request(request: SpawnRequest, *, start_index: int = 1) -> dict[str, Any]:
    return {
        "system": request.system,
        "parent_id": request.parent_id,
        "parent_generation": request.parent_generation,
        "parent_scopes": list(request.parent_scopes),
        "requested_scopes": list(request.requested_scopes),
        "desired_count": request.desired_count,
        "start_index": start_index,
    }


def _load_pending(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping) or payload.get("schema") != PENDING_QUEUE_SCHEMA:
        return []
    rows = payload.get("requests", [])
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _save_pending(path: Path, requests: Sequence[Mapping[str, Any]]) -> None:
    payload = {
        "schema": PENDING_QUEUE_SCHEMA,
        "updated_at": _utc_now(),
        "requests": [dict(row) for row in requests],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def queue_descendant_request(
    *,
    state_dir: str | Path,
    system: str,
    parent_id: str,
    parent_generation: int,
    parent_scopes: Sequence[str],
    desired_count: int,
    requested_scopes: Sequence[str] | None = None,
) -> SpawnRequest:
    """Persist a descendant request for automatic processing in later cycles."""
    inherited = inherited_scopes(parent_scopes, requested_scopes)
    request = request_descendants(
        system=system,
        parent_id=parent_id,
        parent_generation=parent_generation,
        parent_scopes=parent_scopes,
        requested_scopes=inherited,
        desired_count=desired_count,
    )
    _, queue_path = _state_paths(state_dir)
    pending = _load_pending(queue_path)
    pending.append(_serialize_request(request))
    _save_pending(queue_path, pending)
    publish_shared_state(
        state_dir=state_dir,
        actor=system,
        event="descendant_spawn_queued",
        lineage_id=parent_id,
        payload={
            "parent_generation": parent_generation,
            "desired_count": desired_count,
            "effective_scopes": list(inherited),
            "inheritance_mode": "equal_by_default_same_or_narrower",
            "fixed_request_count_ceiling": None,
            "fixed_generation_ceiling": None,
        },
    )
    return request


def _request_from_row(row: Mapping[str, Any]) -> tuple[SpawnRequest, int]:
    request = request_descendants(
        system=str(row["system"]),
        parent_id=str(row["parent_id"]),
        parent_generation=int(row["parent_generation"]),
        parent_scopes=[str(v) for v in row.get("parent_scopes", [])],
        requested_scopes=[str(v) for v in row.get("requested_scopes", [])],
        desired_count=int(row["desired_count"]),
    )
    return request, max(1, int(row.get("start_index", 1)))


def run_closed_loop_cycle(
    *,
    state_dir: str | Path,
    active_agents: int,
    active_limit: int = MAX_ACTIVE_AGENTS,
) -> dict[str, Any]:
    """Process pending descendant requests and persist deferred work for the next cycle."""
    if active_agents < 0:
        raise ClosedLoopFabricError("active_agents cannot be negative")
    if active_limit < 1:
        raise ClosedLoopFabricError("active_limit must be positive")

    _, queue_path = _state_paths(state_dir)
    pending = _load_pending(queue_path)
    remaining: list[dict[str, Any]] = []
    activated: list[dict[str, Any]] = []
    current_active = active_agents

    for raw in pending:
        request, start_index = _request_from_row(raw)
        result = materialize_spawn_request(
            request,
            active_agents=current_active,
            active_limit=active_limit,
            start_index=start_index,
        )
        agents = [dataclasses.asdict(agent) for agent in result.materialized]
        activated.extend(agents)
        current_active += len(agents)

        publish_shared_state(
            state_dir=state_dir,
            actor=request.system,
            event="descendant_spawn_materialized",
            lineage_id=request.parent_id,
            payload={
                "activated": [agent["agent_id"] for agent in agents],
                "activated_count": len(agents),
                "deferred_count": result.deferred_count,
                "effective_scopes": list(request.requested_scopes),
                "inheritance_mode": "equal_by_default_same_or_narrower",
                "raw_credential_inheritance": False,
                "fixed_request_count_ceiling": None,
                "fixed_generation_ceiling": None,
            },
        )

        if result.deferred_count > 0:
            remaining.append({
                **_serialize_request(request, start_index=start_index + len(agents)),
                "desired_count": result.deferred_count,
            })

    _save_pending(queue_path, remaining)
    summary = {
        "activated_count": len(activated),
        "active_agents_after": current_active,
        "pending_requests_after": len(remaining),
        "deferred_descendants_after": sum(int(row["desired_count"]) for row in remaining),
        "shared_state_events": len(read_shared_state(state_dir=state_dir)),
        "next_action": "resume_pending_spawns" if remaining else "observe_share_and_repeat",
        "scope_inheritance": "equal_by_default_same_or_narrower",
        "data_sharing": "shared_append_only_non_secret_state",
        "fixed_recursive_request_count_ceiling": None,
        "fixed_recursive_generation_ceiling": None,
        "raw_credential_inheritance": False,
    }
    publish_shared_state(
        state_dir=state_dir,
        actor="SENJU",
        event="closed_loop_cycle_complete",
        payload=summary,
    )
    return {**summary, "activated": activated}


def report_agent_result(
    *,
    state_dir: str | Path,
    agent_id: str,
    system: str,
    result: Mapping[str, Any],
    lineage_id: str | None = None,
) -> dict[str, Any]:
    """Publish a child result into the shared memory for the next loop iteration."""
    return publish_shared_state(
        state_dir=state_dir,
        actor=system,
        event="agent_result",
        lineage_id=lineage_id or agent_id,
        payload={"agent_id": agent_id, "result": dict(result)},
    )
