"""Issue shared operational capability leases for discovery-authorized targets.

This module turns an already-authorized discovery action queue entry into a concrete,
time-bounded Authority object that META, X, SENJU, child agents, and other AI workers can
consume without a fresh per-target approval.

Authority still comes from the existing owner envelope and its explicit capability
profile. Discovery may activate and renew that pre-authorized capability set for newly
discovered descendants, but it cannot create a new unrelated root, mint credentials, or
broaden capabilities beyond the current action queue.
"""
from __future__ import annotations

import dataclasses
import json
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from .discovery_authorization import _load_json, _normalize_host, _normalize_url

LEASE_SCHEMA = "meta-discovery-capability-leases/v1"
LEASE_EVENT_SCHEMA = "meta-discovery-capability-lease-events/v1"
DEFAULT_LEASE_SECONDS = 6 * 60 * 60
MAX_LEASE_SECONDS = 24 * 60 * 60
SUPPORTED_CAPABILITIES = frozenset(
    {"scan", "probe", "write", "mutation", "credentialed_action"}
)
DEFAULT_CONSUMERS = ("META", "X", "SENJU", "CHILD", "AI")


class DiscoveryCapabilityLeaseError(RuntimeError):
    """Raised when a discovery-derived lease is malformed or no longer authorized."""


@dataclasses.dataclass(frozen=True)
class DiscoveryCapabilityLease:
    lease_id: str
    target: str
    url: str
    authorization_reference: str
    authorization_basis: str | None
    capability_authorization_profile: str | None
    capability_inherited_from_owner_root: bool
    capabilities: tuple[str, ...]
    credential_scope: str
    shared_with: tuple[str, ...]
    issued_at: int
    expires_at: int
    source_action_fingerprint: str
    status: str = "active"

    def is_active(self, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        return self.status == "active" and self.expires_at > current

    def allows(self, capability: str, *, target: str | None = None, now: int | None = None) -> bool:
        if not self.is_active(now=now):
            return False
        if target is not None and _normalize_host(target) != self.target:
            return False
        return str(capability).strip().lower() in self.capabilities


def _action_fingerprint(row: dict[str, Any]) -> str:
    relevant = {
        "target": row.get("target"),
        "url": row.get("url"),
        "authorization_reference": row.get("authorization_reference"),
        "authorization_basis": row.get("authorization_basis"),
        "capabilities": sorted(str(x).strip().lower() for x in row.get("capabilities", [])),
        "credential_scope": row.get("credential_scope", "none"),
        "capability_authorization_profile": row.get("capability_authorization_profile"),
        "capability_inherited_from_owner_root": bool(row.get("capability_inherited_from_owner_root", False)),
    }
    encoded = json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _normalize_action(row: dict[str, Any], *, now: int) -> dict[str, Any] | None:
    if row.get("status") != "ready":
        return None
    try:
        target = _normalize_host(str(row.get("target", "")))
    except ValueError:
        return None
    normalized = _normalize_url(str(row.get("url", "")))
    if normalized is None:
        return None
    url, url_host = normalized
    if url_host != target:
        return None

    try:
        authorization_expiry = int(row.get("expires_at", 0))
    except (TypeError, ValueError):
        return None
    if authorization_expiry <= now:
        return None

    capabilities = tuple(
        sorted(
            {
                str(item).strip().lower()
                for item in row.get("capabilities", [])
                if str(item).strip().lower() in SUPPORTED_CAPABILITIES
            }
        )
    )
    if not capabilities:
        return None

    credential_scope = str(row.get("credential_scope", "none")).strip() or "none"
    if "credentialed_action" in capabilities and credential_scope == "none":
        capabilities = tuple(item for item in capabilities if item != "credentialed_action")
    if not capabilities:
        return None

    reference = str(row.get("authorization_reference", "")).strip()
    if not reference:
        return None
    profile = row.get("capability_authorization_profile")
    if any(cap in {"write", "mutation", "credentialed_action"} for cap in capabilities):
        if not isinstance(profile, str) or not profile.strip():
            capabilities = tuple(cap for cap in capabilities if cap in {"scan", "probe"})
            credential_scope = "none"
    if not capabilities:
        return None

    shared = tuple(
        sorted(
            {
                str(item).strip().upper()
                for item in row.get("shared_with", DEFAULT_CONSUMERS)
                if str(item).strip()
            }
        )
    ) or DEFAULT_CONSUMERS

    return {
        "target": target,
        "url": url,
        "authorization_reference": reference,
        "authorization_basis": (
            str(row.get("authorization_basis"))
            if row.get("authorization_basis") is not None
            else None
        ),
        "capability_authorization_profile": str(profile).strip() if isinstance(profile, str) and profile.strip() else None,
        "capability_inherited_from_owner_root": bool(row.get("capability_inherited_from_owner_root", False)),
        "capabilities": capabilities,
        "credential_scope": credential_scope,
        "shared_with": shared,
        "authorization_expires_at": authorization_expiry,
        "source_action_fingerprint": _action_fingerprint(row),
    }


def _load_leases(path: Path) -> dict[str, DiscoveryCapabilityLease]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict) or payload.get("schema") != LEASE_SCHEMA:
        return {}
    leases: dict[str, DiscoveryCapabilityLease] = {}
    for raw in payload.get("leases", []):
        if not isinstance(raw, dict):
            continue
        try:
            lease = DiscoveryCapabilityLease(
                lease_id=str(raw["lease_id"]),
                target=_normalize_host(str(raw["target"])),
                url=str(raw["url"]),
                authorization_reference=str(raw["authorization_reference"]),
                authorization_basis=(str(raw["authorization_basis"]) if raw.get("authorization_basis") is not None else None),
                capability_authorization_profile=(
                    str(raw["capability_authorization_profile"])
                    if raw.get("capability_authorization_profile") is not None
                    else None
                ),
                capability_inherited_from_owner_root=bool(raw.get("capability_inherited_from_owner_root", False)),
                capabilities=tuple(str(x) for x in raw.get("capabilities", [])),
                credential_scope=str(raw.get("credential_scope", "none")),
                shared_with=tuple(str(x) for x in raw.get("shared_with", [])),
                issued_at=int(raw["issued_at"]),
                expires_at=int(raw["expires_at"]),
                source_action_fingerprint=str(raw["source_action_fingerprint"]),
                status=str(raw.get("status", "active")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        leases[lease.target] = lease
    return leases


def _append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps({"schema": LEASE_EVENT_SCHEMA, **event}, ensure_ascii=False, sort_keys=True) + "\n")


def issue_discovery_capability_leases(
    state_dir: str | Path,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: int | None = None,
) -> dict[str, Any]:
    """Issue/renew concrete Authority leases from the current discovery action queue.

    The current queue is authoritative. A stale lease never preserves capability that
    disappeared from the queue: every cycle reconstructs the lease from the live action
    record and drops targets that are no longer ready or whose underlying authorization
    has expired.
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    ttl = max(300, min(int(lease_seconds), MAX_LEASE_SECONDS))

    queue = _load_json(state / "discovery_action_queue.json", {})
    rows = queue.get("actions", []) if isinstance(queue, dict) else []
    if not isinstance(rows, list):
        rows = []

    lease_path = state / "discovery_capability_leases.json"
    prior = _load_leases(lease_path)
    active: list[DiscoveryCapabilityLease] = []
    events: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_action(row, now=current)
        if normalized is None:
            continue
        target = normalized["target"]
        expires_at = min(current + ttl, int(normalized["authorization_expires_at"]))
        if expires_at <= current:
            continue
        fingerprint = str(normalized["source_action_fingerprint"])
        previous = prior.get(target)
        event_type = "issued"
        if previous is not None:
            event_type = "renewed" if previous.source_action_fingerprint == fingerprint else "replaced"

        lease_id = f"discovery:{target}:{fingerprint[:12]}:{current}"
        lease = DiscoveryCapabilityLease(
            lease_id=lease_id,
            target=target,
            url=str(normalized["url"]),
            authorization_reference=str(normalized["authorization_reference"]),
            authorization_basis=normalized["authorization_basis"],
            capability_authorization_profile=normalized["capability_authorization_profile"],
            capability_inherited_from_owner_root=bool(normalized["capability_inherited_from_owner_root"]),
            capabilities=tuple(normalized["capabilities"]),
            credential_scope=str(normalized["credential_scope"]),
            shared_with=tuple(normalized["shared_with"]),
            issued_at=current,
            expires_at=expires_at,
            source_action_fingerprint=fingerprint,
        )
        active.append(lease)
        events.append(
            {
                "event": event_type,
                "at": current,
                "target": target,
                "lease_id": lease_id,
                "capabilities": list(lease.capabilities),
                "credential_scope": lease.credential_scope,
                "authorization_reference": lease.authorization_reference,
                "capability_authorization_profile": lease.capability_authorization_profile,
                "inherited": lease.capability_inherited_from_owner_root,
            }
        )

    active_targets = {lease.target for lease in active}
    for target, previous in prior.items():
        if target not in active_targets:
            events.append(
                {
                    "event": "dropped",
                    "at": current,
                    "target": target,
                    "lease_id": previous.lease_id,
                    "reason": "not_present_in_live_ready_action_queue",
                }
            )

    active.sort(key=lambda item: item.target)
    payload = {
        "schema": LEASE_SCHEMA,
        "generated_at": current,
        "semantics": "live_action_queue_rebuilds_same_or_narrower_operational_authority",
        "shared_consumers": list(DEFAULT_CONSUMERS),
        "leases": [dataclasses.asdict(lease) for lease in active],
    }
    lease_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_events(state / "capability_lease_events.ndjson", events)

    return {
        "lease_count": len(active),
        "high_impact_lease_count": sum(
            1
            for lease in active
            if set(lease.capabilities) & {"write", "mutation", "credentialed_action"}
        ),
        "inherited_high_impact_lease_count": sum(
            1
            for lease in active
            if lease.capability_inherited_from_owner_root
            and set(lease.capabilities) & {"write", "mutation", "credentialed_action"}
        ),
        "credentialed_lease_count": sum(
            1 for lease in active if "credentialed_action" in lease.capabilities
        ),
        "event_count": len(events),
    }


def load_discovery_capability_leases(state_dir: str | Path) -> tuple[DiscoveryCapabilityLease, ...]:
    leases = _load_leases(Path(state_dir) / "discovery_capability_leases.json")
    return tuple(sorted(leases.values(), key=lambda item: item.target))


def authorize_discovery_capability(
    state_dir: str | Path,
    *,
    target: str,
    capability: str,
    now: int | None = None,
) -> DiscoveryCapabilityLease:
    """Return the active exact-target lease or fail closed for an executor."""
    normalized_target = _normalize_host(target)
    normalized_capability = str(capability).strip().lower()
    for lease in load_discovery_capability_leases(state_dir):
        if lease.target != normalized_target:
            continue
        if lease.allows(normalized_capability, target=normalized_target, now=now):
            return lease
        raise DiscoveryCapabilityLeaseError(
            f"capability is not active for target: {normalized_capability} -> {normalized_target}"
        )
    raise DiscoveryCapabilityLeaseError(f"no active discovery capability lease for target: {normalized_target}")
