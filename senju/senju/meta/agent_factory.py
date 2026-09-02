"""Bounded META/X child-agent factory.

META and X may each maintain a direct fleet of up to ten child workers. Children
receive revocable delegated capability grants derived from the parent's allowed
scope; raw credentials/secrets are never copied into child records.

Children may request descendants through the recursive spawn broker, but they
cannot directly mint agents or credentials themselves. This preserves recursive
agent topology while keeping activation and grant issuance centrally bounded.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

MAX_CHILDREN_PER_PARENT = 10
ROOT_SYSTEMS = frozenset({"META", "X"})
REGISTRY_SCHEMA = "senju-meta-x-agent-factory/v1"


@dataclasses.dataclass(frozen=True)
class DelegatedGrant:
    grant_id: str
    scopes: tuple[str, ...]
    revocable: bool = True
    raw_credential_inherited: bool = False


@dataclasses.dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    system: str
    parent_id: str
    generation: int
    grant: DelegatedGrant
    may_spawn_children: bool = False
    status: str = "provisioned"


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    cleaned = tuple(sorted({str(scope).strip() for scope in scopes if str(scope).strip()}))
    if not cleaned:
        raise ValueError("at least one delegated scope is required")
    return cleaned


def _derive_grant(parent_id: str, agent_id: str, parent_scopes: Sequence[str], requested_scopes: Sequence[str] | None) -> DelegatedGrant:
    parent = set(_normalize_scopes(parent_scopes))
    requested = set(_normalize_scopes(requested_scopes if requested_scopes is not None else parent_scopes))
    if not requested.issubset(parent):
        raise PermissionError("child grant may not exceed parent scope")
    material = f"{parent_id}|{agent_id}|{'|'.join(sorted(requested))}"
    grant_id = "grant-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return DelegatedGrant(grant_id=grant_id, scopes=tuple(sorted(requested)))


def spawn_children(
    *,
    system: str,
    parent_id: str,
    parent_scopes: Sequence[str],
    count: int = MAX_CHILDREN_PER_PARENT,
    requested_scopes: Sequence[str] | None = None,
    parent_generation: int = 0,
) -> list[AgentSpec]:
    """Create bounded direct children for a META or X root.

    Direct materialization remains root-only and bounded to ten children. The
    children are marked as eligible to submit recursive spawn requests to the
    broker. They still cannot directly mint descendants or raw credentials.
    """
    normalized_system = system.strip().upper()
    if normalized_system not in ROOT_SYSTEMS:
        raise PermissionError("only META and X roots may use the shared child factory")
    if parent_generation != 0:
        raise PermissionError("recursive direct spawning is disabled; use the spawn broker")
    if count < 1 or count > MAX_CHILDREN_PER_PARENT:
        raise ValueError(f"count must be between 1 and {MAX_CHILDREN_PER_PARENT}")
    if not parent_id.strip():
        raise ValueError("parent_id is required")

    children: list[AgentSpec] = []
    for index in range(1, count + 1):
        agent_id = f"{normalized_system}-CHILD-{index:02d}"
        grant = _derive_grant(parent_id, agent_id, parent_scopes, requested_scopes)
        children.append(
            AgentSpec(
                agent_id=agent_id,
                system=normalized_system,
                parent_id=parent_id,
                generation=1,
                grant=grant,
                may_spawn_children=True,
            )
        )
    return children


def ensure_direct_fleet(
    registry_path: str | Path,
    *,
    system: str,
    parent_id: str,
    parent_scopes: Sequence[str],
    count: int = MAX_CHILDREN_PER_PARENT,
    requested_scopes: Sequence[str] | None = None,
) -> dict:
    """Idempotently persist one bounded direct fleet.

    Re-running the META loop updates the same parent fleet rather than multiplying
    the number of live agents on every cycle.
    """
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            registry = {}
    else:
        registry = {}

    if registry.get("schema") != REGISTRY_SCHEMA:
        registry = {"schema": REGISTRY_SCHEMA, "parents": {}}
    parents = registry.setdefault("parents", {})
    fleet = spawn_children(
        system=system,
        parent_id=parent_id,
        parent_scopes=parent_scopes,
        count=count,
        requested_scopes=requested_scopes,
        parent_generation=0,
    )
    parents[parent_id] = {
        "system": system.strip().upper(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "max_children": MAX_CHILDREN_PER_PARENT,
        "children": [dataclasses.asdict(child) for child in fleet],
    }
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    return parents[parent_id]


def revoke_child(registry_path: str | Path, *, parent_id: str, agent_id: str) -> bool:
    """Revoke one child without rotating every sibling's grant."""
    path = Path(registry_path)
    if not path.exists():
        return False
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    parent = (registry.get("parents") or {}).get(parent_id)
    if not isinstance(parent, Mapping):
        return False
    children = parent.get("children")
    if not isinstance(children, list):
        return False
    changed = False
    for child in children:
        if isinstance(child, dict) and child.get("agent_id") == agent_id:
            child["status"] = "revoked"
            changed = True
    if changed:
        path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    return changed
