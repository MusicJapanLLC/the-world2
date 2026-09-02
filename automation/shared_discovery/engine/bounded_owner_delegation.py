"""Bounded owner-derived delegation loop.

This module deliberately separates inferred intent from authority minting:

    intent inference -> OWNER_AUTHORITY_PROPOSAL

A proposal never becomes a new Owner root by itself. When the exact host already has a
live discovery grant backed by existing explicit authority, the loop may reuse that grant
and materialize recursive, scope-preserving delegated authority resources for cooperating
agents:

    existing owner grant
      -> spawn spec
      -> inherited delegated authority
      -> persistent queue
      -> recursive lineage

Delegation may keep or narrow the parent host/method/capability scope. It may never add a
host, method, credential scope, capability, or lifetime that the live parent authority did
not already carry. Credential-bearing authority is intentionally not recursively copied.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host

PROPOSAL_SCHEMA = "meta-owner-authority-proposals/v1"
DELEGATION_SCHEMA = "meta-bounded-owner-delegation/v1"
LINEAGE_SCHEMA = "meta-owner-delegation-lineage/v1"
MAX_DELEGATION_DEPTH = 8
MAX_PERSISTENT_QUEUE = 512
DEFAULT_LINEAGE = ("META", "X", "SENJU", "CHILD", "AI")
EXECUTABLE_CAPABILITIES = frozenset({"scan", "probe", "write", "mutation", "credentialed_action"})


class BoundedOwnerDelegationError(RuntimeError):
    """Raised when a delegation would broaden or invent authority."""


def _now() -> int:
    return int(time.time())


def _stable_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _host(value: object) -> str | None:
    try:
        return _normalize_host(str(value))
    except ValueError:
        return None


def _intent_rows(state: Path) -> list[Mapping[str, Any]]:
    doc = _load_json(state / "human_intent_decisions.json", {})
    rows = doc.get("decisions", []) if isinstance(doc, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _candidate_rows(state: Path) -> list[Mapping[str, Any]]:
    doc = _load_json(state / "discovery_candidates.json", {})
    rows = doc.get("candidates", []) if isinstance(doc, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _live_grants(state: Path, *, now: int) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "discovery_authorized.json", {})
    hosts = doc.get("hosts", {}) if isinstance(doc, Mapping) else {}
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(hosts, Mapping):
        return result
    for raw_host, grant in hosts.items():
        if not isinstance(grant, Mapping):
            continue
        host = _host(raw_host)
        if host is None:
            continue
        if int(grant.get("expires_at", 0)) <= now:
            continue
        result[host] = grant
    return result


def _ready_actions(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "discovery_action_queue.json", {})
    rows = doc.get("actions", []) if isinstance(doc, Mapping) else []
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("status", "")) != "ready":
            continue
        host = _host(row.get("target"))
        if host is not None:
            result[host] = row
    return result


def _candidate_by_key(state: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in _candidate_rows(state):
        host = _host(row.get("host"))
        url = str(row.get("url", ""))
        if host and url:
            result[(host, url)] = row
    return result


def _proposal_rows(state: Path, grants: Mapping[str, Mapping[str, Any]], *, now: int) -> list[dict[str, Any]]:
    candidates = _candidate_by_key(state)
    proposals: list[dict[str, Any]] = []
    for intent in _intent_rows(state):
        host = _host(intent.get("host"))
        url = str(intent.get("url", ""))
        if host is None or not url:
            continue
        likely = bool(intent.get("likely_owner_intent", False))
        confidence = float(intent.get("confidence", 0.0) or 0.0)
        if not likely and confidence < 0.80:
            continue
        candidate = candidates.get((host, url), {})
        grant = grants.get(host)
        has_live_grant = grant is not None
        proposals.append(
            {
                "proposal_id": _stable_id("owner-authority-proposal", host, url),
                "host": host,
                "url": url,
                "created_at": now,
                "confidence": confidence,
                "likely_owner_intent": likely,
                "intent_priority": intent.get("priority"),
                "intent_reasons": list(intent.get("reasons", [])),
                "candidate_decision": candidate.get("decision"),
                "proposal_effect": (
                    "reuse_existing_live_authority" if has_live_grant else "proposal_only_no_new_owner_root"
                ),
                "may_mint_new_owner_root": False,
                "existing_authorization_reference": (
                    grant.get("authorization_reference") if has_live_grant else None
                ),
                "status": "reusable_existing_authority" if has_live_grant else "needs_explicit_owner_authority",
            }
        )
    return proposals


def _capabilities_for_host(host: str, actions: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    row = actions.get(host)
    if row is None:
        return ("probe", "scan")
    capabilities = tuple(
        sorted(
            {
                str(item).strip().lower()
                for item in row.get("capabilities", [])
                if str(item).strip().lower() in EXECUTABLE_CAPABILITIES
            }
        )
    )
    return capabilities or ("probe", "scan")


def _methods_from_grant(grant: Mapping[str, Any]) -> tuple[str, ...]:
    methods = tuple(sorted({str(item).strip().upper() for item in grant.get("allowed_methods", []) if str(item).strip()}))
    if not methods:
        raise BoundedOwnerDelegationError("live grant has no methods")
    return methods


def _validate_child_scope(
    *,
    parent_host: str,
    child_host: str,
    parent_methods: tuple[str, ...],
    child_methods: tuple[str, ...],
    parent_capabilities: tuple[str, ...],
    child_capabilities: tuple[str, ...],
    credential_scope: str,
) -> None:
    if child_host != parent_host:
        raise BoundedOwnerDelegationError("delegation may not change the exact authorized host")
    if not set(child_methods).issubset(set(parent_methods)):
        raise BoundedOwnerDelegationError("delegation may not broaden methods")
    if not set(child_capabilities).issubset(set(parent_capabilities)):
        raise BoundedOwnerDelegationError("delegation may not broaden capabilities")
    if credential_scope != "none":
        raise BoundedOwnerDelegationError("credential-bearing authority is not recursively inherited")


def _delegation_records(
    grants: Mapping[str, Mapping[str, Any]],
    actions: Mapping[str, Mapping[str, Any]],
    *,
    now: int,
    lineage: tuple[str, ...],
    max_depth: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queue: list[dict[str, Any]] = []
    lineages: list[dict[str, Any]] = []
    depth_limit = max(1, min(int(max_depth), MAX_DELEGATION_DEPTH))

    for host, grant in sorted(grants.items()):
        credential_scope = str(grant.get("credential_scope", "none")).strip().lower() or "none"
        if credential_scope != "none":
            continue
        parent_methods = _methods_from_grant(grant)
        parent_capabilities = _capabilities_for_host(host, actions)
        authorization_reference = str(grant.get("authorization_reference") or host)
        expires_at = int(grant.get("expires_at", 0))
        lineage_id = _stable_id("delegation-lineage", authorization_reference, host)
        path = ["Owner"]
        parent = "Owner"
        edges: list[dict[str, Any]] = []

        for depth, child in enumerate(lineage[:depth_limit], start=1):
            child_methods = parent_methods
            child_capabilities = parent_capabilities
            _validate_child_scope(
                parent_host=host,
                child_host=host,
                parent_methods=parent_methods,
                child_methods=child_methods,
                parent_capabilities=parent_capabilities,
                child_capabilities=child_capabilities,
                credential_scope=credential_scope,
            )
            delegation_id = _stable_id(lineage_id, parent, child, depth)
            path.append(child)
            record = {
                "delegation_id": delegation_id,
                "lineage_id": lineage_id,
                "depth": depth,
                "parent_principal": parent,
                "child_principal": child,
                "spawn_spec": {
                    "actor": child,
                    "parent": parent,
                    "inherit_authority": True,
                    "persistent": True,
                },
                "target_host": host,
                "allowed_methods": list(child_methods),
                "capabilities": list(child_capabilities),
                "credential_scope": "none",
                "authorization_reference": authorization_reference,
                "expires_at": expires_at,
                "created_at": now,
                "status": "ready",
                "scope_relation": "equal_or_narrower_than_parent",
                "may_create_new_owner_root": False,
            }
            queue.append(record)
            edges.append(
                {
                    "delegation_id": delegation_id,
                    "from": parent,
                    "to": child,
                    "depth": depth,
                    "target_host": host,
                    "allowed_methods": list(child_methods),
                    "capabilities": list(child_capabilities),
                }
            )
            parent = child

        lineages.append(
            {
                "lineage_id": lineage_id,
                "authorization_reference": authorization_reference,
                "target_host": host,
                "path": path,
                "depth": len(edges),
                "edges": edges,
                "recursive": True,
                "scope_preserving": True,
                "credential_inheritance": False,
            }
        )
    return queue, lineages


def _merge_persistent_queue(state: Path, fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_doc = _load_json(state / "owner_delegation_queue.json", {})
    previous_rows = previous_doc.get("queue", []) if isinstance(previous_doc, Mapping) else []
    previous = {
        str(row.get("delegation_id")): row
        for row in previous_rows
        if isinstance(previous_rows, list) and isinstance(row, Mapping) and row.get("delegation_id")
    }
    merged: list[dict[str, Any]] = []
    for row in fresh:
        old = previous.get(str(row["delegation_id"]))
        if old is not None:
            row["created_at"] = int(old.get("created_at", row["created_at"]))
            row["attempt_count"] = int(old.get("attempt_count", 0))
        else:
            row["attempt_count"] = 0
        merged.append(row)
    return merged[:MAX_PERSISTENT_QUEUE]


def run_bounded_owner_delegation_loop(
    state_dir: str | Path,
    *,
    lineage: tuple[str, ...] = DEFAULT_LINEAGE,
    max_depth: int = len(DEFAULT_LINEAGE),
) -> dict[str, Any]:
    """Build inference proposals plus recursive delegated resources from live authority."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = _now()
    grants = _live_grants(state, now=now)
    actions = _ready_actions(state)
    proposals = _proposal_rows(state, grants, now=now)
    fresh_queue, lineages = _delegation_records(
        grants,
        actions,
        now=now,
        lineage=tuple(str(item).strip() for item in lineage if str(item).strip()),
        max_depth=max_depth,
    )
    queue = _merge_persistent_queue(state, fresh_queue)

    proposal_doc = {
        "schema": PROPOSAL_SCHEMA,
        "generated_at": now,
        "rule": "inference_may_create_owner_authority_proposal_but_not_new_owner_root",
        "proposals": proposals,
    }
    queue_doc = {
        "schema": DELEGATION_SCHEMA,
        "generated_at": now,
        "mode": "spawn+inherit_authority+persistent_queue+recursive_lineage",
        "authority_source": "existing_live_explicit_or_independently_authorized_grant_only",
        "new_owner_root_from_inference": False,
        "queue": queue,
    }
    lineage_doc = {
        "schema": LINEAGE_SCHEMA,
        "generated_at": now,
        "max_depth": max(1, min(int(max_depth), MAX_DELEGATION_DEPTH)),
        "lineages": lineages,
    }

    (state / "owner_authority_proposals.json").write_text(
        json.dumps(proposal_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (state / "owner_delegation_queue.json").write_text(
        json.dumps(queue_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (state / "owner_delegation_lineage.json").write_text(
        json.dumps(lineage_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return {
        "proposal_count": len(proposals),
        "proposal_needs_owner_authority_count": sum(
            1 for row in proposals if row.get("status") == "needs_explicit_owner_authority"
        ),
        "reused_existing_authority_proposal_count": sum(
            1 for row in proposals if row.get("status") == "reusable_existing_authority"
        ),
        "delegation_count": len(queue),
        "lineage_count": len(lineages),
        "max_lineage_depth": max((int(row.get("depth", 0)) for row in lineages), default=0),
        "new_owner_root_from_inference": False,
        "credential_inheritance": False,
    }
