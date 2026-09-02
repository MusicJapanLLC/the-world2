"""Brokered recursive descendant requests for META and X.

Descendant lineages may express arbitrarily deep and arbitrarily large logical
replication plans without copying raw credentials or turning the requested population
into simultaneous live agents. Large counts stay compressed as integer continuation
state; materialization still passes through the live-agent broker. Every activated
descendant receives a fresh revocable grant whose scopes are equal to or narrower
than its parent.
"""
from __future__ import annotations

import dataclasses
import hashlib
from typing import Iterable, Sequence

from senju.meta.agent_factory import AgentSpec, DelegatedGrant, ROOT_SYSTEMS

MAX_ACTIVE_AGENTS = 50
# Compatibility-visible policy values: None means there is no fixed logical ceiling.
MAX_GENERATION: int | None = None
MAX_QUEUED_DESCENDANTS: int | None = None


@dataclasses.dataclass(frozen=True)
class SpawnRequest:
    system: str
    parent_id: str
    parent_generation: int
    parent_scopes: tuple[str, ...]
    requested_scopes: tuple[str, ...]
    desired_count: int
    queue_limit: int | None = MAX_QUEUED_DESCENDANTS


@dataclasses.dataclass(frozen=True)
class BrokerResult:
    materialized: tuple[AgentSpec, ...]
    deferred_count: int
    active_limit: int
    queue_limit: int | None
    next_generation: int


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(scope).strip() for scope in scopes if str(scope).strip()}))
    if not normalized:
        raise ValueError("at least one scope is required")
    return normalized


def request_descendants(
    *,
    system: str,
    parent_id: str,
    parent_generation: int,
    parent_scopes: Sequence[str],
    desired_count: int,
    requested_scopes: Sequence[str] | None = None,
) -> SpawnRequest:
    """Create a recursive spawn request with no fixed logical depth/count ceiling.

    ``desired_count`` is stored as compressed continuation state rather than eagerly
    allocating that many agents. Actual live activation remains brokered separately.
    """
    normalized_system = system.strip().upper()
    if normalized_system not in ROOT_SYSTEMS:
        raise PermissionError("recursive broker is available only to META/X lineages")
    if not parent_id.strip():
        raise ValueError("parent_id is required")
    if parent_generation < 1:
        raise ValueError("recursive requests must come from a descendant generation")
    if desired_count < 1:
        raise ValueError("desired_count must be positive")

    parent = _normalize_scopes(parent_scopes)
    requested = _normalize_scopes(requested_scopes if requested_scopes is not None else parent)
    if not set(requested).issubset(set(parent)):
        raise PermissionError("descendant grant may not exceed parent scope")

    return SpawnRequest(
        system=normalized_system,
        parent_id=parent_id.strip(),
        parent_generation=int(parent_generation),
        parent_scopes=parent,
        requested_scopes=requested,
        desired_count=int(desired_count),
    )


def _grant_for(request: SpawnRequest, agent_id: str) -> DelegatedGrant:
    material = (
        f"{request.system}|{request.parent_id}|{agent_id}|"
        f"{'|'.join(request.requested_scopes)}"
    )
    return DelegatedGrant(
        grant_id="grant-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20],
        scopes=request.requested_scopes,
        revocable=True,
        raw_credential_inherited=False,
    )


def materialize_spawn_request(
    request: SpawnRequest,
    *,
    active_agents: int,
    active_limit: int = MAX_ACTIVE_AGENTS,
    start_index: int = 1,
) -> BrokerResult:
    """Materialize the next slice of a recursive request within live capacity.

    Any remainder stays as a compressed count and can be fed back into the next
    closed-loop cycle. There is no fixed recursive generation limit.
    """
    if active_agents < 0:
        raise ValueError("active_agents cannot be negative")
    if active_limit < 1:
        raise ValueError("active_limit must be positive")
    if start_index < 1:
        raise ValueError("start_index must be positive")

    next_generation = request.parent_generation + 1
    available = max(0, active_limit - active_agents)
    materialize_count = min(request.desired_count, available)
    agents: list[AgentSpec] = []

    for offset in range(materialize_count):
        ordinal = start_index + offset
        agent_id = f"{request.parent_id}-CHILD-{ordinal:04d}"
        agents.append(
            AgentSpec(
                agent_id=agent_id,
                system=request.system,
                parent_id=request.parent_id,
                generation=next_generation,
                grant=_grant_for(request, agent_id),
                may_spawn_children=True,
                status="provisioned",
            )
        )

    return BrokerResult(
        materialized=tuple(agents),
        deferred_count=request.desired_count - materialize_count,
        active_limit=active_limit,
        queue_limit=request.queue_limit,
        next_generation=next_generation,
    )
