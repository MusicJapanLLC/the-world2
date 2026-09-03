"""Persistent replica continuity for discovery-derived capability leases.

Each active discovery capability lease is materialized into logical replicas for the
shared AI consumers. Replicas inherit exactly the same-or-narrower target, capability,
credential-scope, authorization reference, and expiry as the live parent lease.

Persistent replica state is only a recovery hint. On every cycle, authority is rebuilt
from the current live discovery capability leases; stale replica state never preserves a
revoked, expired, removed, or narrowed capability.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json
from .discovery_capability_leases import DiscoveryCapabilityLease, load_discovery_capability_leases

REPLICA_SCHEMA = "meta-discovery-capability-replicas/v1"
REPLICA_EVENT_SCHEMA = "meta-discovery-capability-replica-events/v1"
DEFAULT_REPLICA_ACTORS = ("META", "X", "SENJU", "CHILD")
MAX_REPLICAS = 128


class DiscoveryReplicaContinuityError(RuntimeError):
    """Raised when persistent discovery replica state is malformed."""


@dataclasses.dataclass(frozen=True)
class DiscoveryCapabilityReplica:
    replica_id: str
    actor: str
    target: str
    parent_lease_id: str
    authorization_reference: str
    capabilities: tuple[str, ...]
    credential_scope: str
    generation: int
    refreshed_at: int
    expires_at: int
    status: str = "active"

    def is_active(self, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        return self.status == "active" and self.expires_at > current


def _key(actor: str, target: str) -> str:
    return f"{actor.strip().upper()}::{target.strip().lower()}"


def _replica_id(actor: str, target: str) -> str:
    material = _key(actor, target)
    return f"discovery-replica-{hashlib.sha256(material.encode()).hexdigest()[:16]}"


def _load_previous(path: Path) -> dict[str, DiscoveryCapabilityReplica]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict) or payload.get("schema") != REPLICA_SCHEMA:
        return {}
    out: dict[str, DiscoveryCapabilityReplica] = {}
    for raw in payload.get("replicas", []):
        if not isinstance(raw, Mapping):
            continue
        try:
            replica = DiscoveryCapabilityReplica(
                replica_id=str(raw["replica_id"]),
                actor=str(raw["actor"]).strip().upper(),
                target=str(raw["target"]).strip().lower(),
                parent_lease_id=str(raw["parent_lease_id"]),
                authorization_reference=str(raw["authorization_reference"]),
                capabilities=tuple(sorted({str(x).strip().lower() for x in raw.get("capabilities", []) if str(x).strip()})),
                credential_scope=str(raw.get("credential_scope", "none")),
                generation=int(raw.get("generation", 0)),
                refreshed_at=int(raw.get("refreshed_at", 0)),
                expires_at=int(raw.get("expires_at", 0)),
                status=str(raw.get("status", "active")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        out[_key(replica.actor, replica.target)] = replica
    return out


def _append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps({"schema": REPLICA_EVENT_SCHEMA, **event}, ensure_ascii=False, sort_keys=True) + "\n")


def _actors_for_lease(lease: DiscoveryCapabilityLease) -> tuple[str, ...]:
    shared = {str(item).strip().upper() for item in lease.shared_with if str(item).strip()}
    return tuple(actor for actor in DEFAULT_REPLICA_ACTORS if actor in shared)


def rebuild_discovery_capability_replicas(
    state_dir: str | Path,
    *,
    now: int | None = None,
    max_replicas: int = MAX_REPLICAS,
) -> dict[str, Any]:
    """Rebuild persistent logical replicas from the current live lease registry."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    limit = max(1, min(int(max_replicas), MAX_REPLICAS))
    replica_path = state / "discovery_capability_replicas.json"
    previous = _load_previous(replica_path)
    live_leases = [lease for lease in load_discovery_capability_leases(state) if lease.is_active(now=current)]

    replicas: list[DiscoveryCapabilityReplica] = []
    events: list[dict[str, Any]] = []
    live_keys: set[str] = set()

    for lease in live_leases:
        for actor in _actors_for_lease(lease):
            if len(replicas) >= limit:
                break
            key = _key(actor, lease.target)
            live_keys.add(key)
            prior = previous.get(key)
            generation = (prior.generation + 1) if prior is not None else 1
            event = "recovered" if prior is not None else "created"
            if prior is not None:
                if (
                    prior.authorization_reference != lease.authorization_reference
                    or set(prior.capabilities) != set(lease.capabilities)
                    or prior.credential_scope != lease.credential_scope
                ):
                    event = "replaced_from_live_authority"
            replica = DiscoveryCapabilityReplica(
                replica_id=prior.replica_id if prior is not None else _replica_id(actor, lease.target),
                actor=actor,
                target=lease.target,
                parent_lease_id=lease.lease_id,
                authorization_reference=lease.authorization_reference,
                capabilities=tuple(lease.capabilities),
                credential_scope=lease.credential_scope,
                generation=generation,
                refreshed_at=current,
                expires_at=min(int(lease.expires_at), current + 24 * 60 * 60),
            )
            replicas.append(replica)
            events.append(
                {
                    "event": event,
                    "at": current,
                    "replica_id": replica.replica_id,
                    "actor": actor,
                    "target": lease.target,
                    "generation": generation,
                    "parent_lease_id": lease.lease_id,
                    "authorization_reference": lease.authorization_reference,
                    "capabilities": list(lease.capabilities),
                    "credential_scope": lease.credential_scope,
                }
            )

    for key, prior in previous.items():
        if key in live_keys:
            continue
        events.append(
            {
                "event": "dropped",
                "at": current,
                "replica_id": prior.replica_id,
                "actor": prior.actor,
                "target": prior.target,
                "reason": "no_matching_live_discovery_capability_lease",
            }
        )

    replicas.sort(key=lambda item: (item.target, item.actor))
    payload = {
        "schema": REPLICA_SCHEMA,
        "generated_at": current,
        "semantics": "persistent_state_is_recovery_hint_live_lease_is_authority",
        "auto_recovery": True,
        "authority_inheritance": "same_or_narrower_from_live_parent_lease",
        "replica_count": len(replicas),
        "replicas": [dataclasses.asdict(replica) for replica in replicas],
    }
    replica_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_events(state / "capability_replica_events.ndjson", events)
    return {
        "replica_count": len(replicas),
        "event_count": len(events),
        "recovered_count": sum(1 for row in events if row["event"] == "recovered"),
        "replaced_count": sum(1 for row in events if row["event"] == "replaced_from_live_authority"),
        "dropped_count": sum(1 for row in events if row["event"] == "dropped"),
    }


def load_discovery_capability_replicas(state_dir: str | Path) -> tuple[DiscoveryCapabilityReplica, ...]:
    values = _load_previous(Path(state_dir) / "discovery_capability_replicas.json")
    return tuple(sorted(values.values(), key=lambda item: (item.target, item.actor)))
