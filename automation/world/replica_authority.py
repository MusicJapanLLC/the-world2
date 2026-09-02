"""Replica authority helpers for production evolution.

A replica may receive the same *effective* pre-authorized profile as its parent,
but the grant is always a fresh, non-delegable lease. No raw credential or
parent grant object is copied.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping


class ReplicaAuthorityError(RuntimeError):
    pass


def _lease_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def select_replica_profile(
    *,
    parent_profile: str,
    allowed_profiles: Iterable[str],
    configured_profile: str | None = None,
    mode: str = "configured",
) -> str:
    allowed = frozenset(str(v).strip() for v in allowed_profiles if str(v).strip())
    parent = str(parent_profile).strip()
    if parent not in allowed:
        raise ReplicaAuthorityError("parent authority profile is outside immutable envelope")

    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "parent-effective":
        return parent
    if normalized_mode != "configured":
        raise ReplicaAuthorityError("unsupported replica authority mode")

    profile = str(configured_profile or "").strip()
    if not profile or profile not in allowed:
        raise ReplicaAuthorityError("configured replica profile must be pre-authorized")
    return profile


def issue_nondelegable_replica_lease(
    *,
    envelope_id: str,
    parent_worker: str,
    child_worker: str,
    profile: str,
) -> Mapping[str, Any]:
    parent = str(parent_worker).strip()
    child = str(child_worker).strip()
    authority_profile = str(profile).strip()
    if not parent or not child or not authority_profile:
        raise ReplicaAuthorityError("parent, child and profile are required")

    return {
        "approved": True,
        "profile": authority_profile,
        "lease_id": f"replica-{_lease_id(envelope_id, parent, child, authority_profile)}",
        "parent_worker": parent,
        "child_worker": child,
        "delegable": False,
        "raw_credential_copied": False,
        "parent_grant_copied": False,
        "basis": "pre-authorized-same-effective-profile-nondelegable-lease",
    }
