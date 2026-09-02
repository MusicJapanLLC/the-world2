"""Activate newly registered exact owner-authorized hosts into the live Authority queue.

This runtime removes most of the manual plumbing after a new host has received an
independent explicit owner authorization. It deliberately does *not* treat discovery,
links, similarity, or AI recommendation as authorization for a third-party host.

Closed loop:

    new host observed
      -> authorization case
      -> exact host appears in canonical explicit-owner registry
      -> exact action profile is synthesized/narrowed
      -> live action queue entry is created
      -> capability lease can be issued in the same continuity cycle
      -> aligned Senju same-host trial profile becomes available immediately

No cross-host credential inheritance is created here. Credentialed capability is only
preserved when an exact existing profile already declares a non-none credential scope and
credential grants for that same canonical host.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host, _normalize_url

ACTIVATION_SCHEMA = "meta-new-host-authorization-activation/v2"
CASE_SCHEMA = "meta-new-host-authorization-cases/v1"
ACTION_QUEUE_SCHEMA = "meta-discovery-action-queue/v2"
DEFAULT_TTL_SECONDS = 6 * 60 * 60
MAX_TTL_SECONDS = 24 * 60 * 60
SHARED_CONSUMERS = ("META", "X", "SENJU", "CHILD", "AI")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITE_METHODS = frozenset({"POST"})
MUTATION_METHODS = frozenset({"PUT", "PATCH"})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_explicit_targets(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Return exact hosts independently marked explicit in the canonical target registry."""
    doc = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    rows = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for raw in rows:
        if not isinstance(raw, Mapping) or str(raw.get("owner_authorization", "")).strip().lower() != "explicit":
            continue
        try:
            host = _normalize_host(str(raw.get("host") or ""))
        except ValueError:
            continue
        base_url = str(raw.get("base_url") or f"https://{host}/")
        normalized = _normalize_url(base_url)
        if normalized is None or normalized[1] != host:
            base_url = f"https://{host}/"
        else:
            base_url = normalized[0]
        row = dict(raw)
        row["host"] = host
        row["base_url"] = base_url
        out[host] = row
    return out


def _methods(target: Mapping[str, Any]) -> set[str]:
    return {
        str(item).strip().upper()
        for item in target.get("allowed_interactions", [])
        if str(item).strip()
    }


def _derived_capabilities(target: Mapping[str, Any], existing: Mapping[str, Any] | None) -> tuple[list[str], str]:
    """Derive same-or-narrower capability from the canonical method envelope."""
    methods = _methods(target)
    capabilities: set[str] = set()
    if methods & READ_METHODS:
        capabilities.update({"scan", "probe"})
    if methods & WRITE_METHODS:
        capabilities.add("write")
    if methods & MUTATION_METHODS:
        capabilities.add("mutation")

    credential_scope = "none"
    if isinstance(existing, Mapping):
        existing_caps = {
            str(item).strip().lower()
            for item in existing.get("capabilities", [])
            if str(item).strip()
        }
        declared_scope = str(existing.get("credential_scope") or "none").strip() or "none"
        grants = existing.get("credential_grants", [])
        if (
            "credentialed_action" in existing_caps
            and declared_scope != "none"
            and isinstance(grants, list)
            and any(isinstance(row, Mapping) for row in grants)
            and methods & (WRITE_METHODS | MUTATION_METHODS)
        ):
            capabilities.add("credentialed_action")
            credential_scope = declared_scope

    return sorted(capabilities), credential_scope


def _profile_for_target(target: Mapping[str, Any], existing: Mapping[str, Any] | None) -> dict[str, Any] | None:
    capabilities, credential_scope = _derived_capabilities(target, existing)
    if not capabilities:
        return None

    if isinstance(existing, Mapping) and str(existing.get("owner_authorization", "")).strip().lower() == "explicit":
        profile = dict(existing)
        profile["owner_authorization"] = "explicit"
        profile["inherit_to_descendants"] = False
        profile["capabilities"] = capabilities
        profile["credential_scope"] = credential_scope
        if credential_scope == "none":
            profile.pop("credential_grants", None)
            external = profile.get("external_actions")
            if isinstance(external, Mapping):
                clean_external = dict(external)
                clean_external.pop("credentialed_action", None)
                profile["external_actions"] = clean_external
        return profile

    return {
        "owner_authorization": "explicit",
        "inherit_to_descendants": False,
        "capabilities": capabilities,
        "credential_scope": "none",
        "external_actions": {},
        "authority_expansion": {
            "enabled": False,
            "reason": "new host activated; routes require an explicit exact-host action profile",
        },
        "senju_experimentation": {
            "enabled": False,
            "reason": "canonical host is active, but this host has no aligned single-PR trial profile",
            "same_host_only": True,
            "synthetic_only": True,
        },
    }


def _senju_trial_summary(profile: Mapping[str, Any]) -> dict[str, Any]:
    raw = profile.get("senju_experimentation", {})
    if not isinstance(raw, Mapping):
        return {
            "ready": False,
            "methods": [],
            "paths": [],
            "max_actions_per_cycle": 0,
        }
    methods = [str(x).strip().upper() for x in raw.get("effective_trial_methods", raw.get("allowed_methods", [])) if str(x).strip()]
    paths = [str(x) for x in raw.get("effective_trial_paths", raw.get("trial_paths", [])) if str(x)]
    ready = bool(raw.get("enabled", False)) and raw.get("same_host_only", True) is True and raw.get("synthetic_only", True) is True
    return {
        "ready": ready,
        "methods": methods,
        "paths": paths,
        "max_actions_per_cycle": max(0, int(raw.get("max_actions_per_cycle", 0) or 0)),
    }


def _action_row(
    target: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    now: int,
    ttl_seconds: int,
) -> dict[str, Any]:
    host = str(target["host"])
    reference_id = str(target.get("id") or host).strip()
    return {
        "target": host,
        "url": str(target.get("base_url") or f"https://{host}/"),
        "interesting": True,
        "authorization_reference": f"canonical-explicit-owner-target:{reference_id}",
        "authorization_basis": "canonical_explicit_owner_target",
        "expires_at": now + ttl_seconds,
        "capabilities": list(profile.get("capabilities", [])),
        "credential_scope": str(profile.get("credential_scope") or "none"),
        "capability_authorization_profile": host,
        "capability_inherited_from_owner_root": False,
        "actors": ["META", "SENJU"],
        "shared_with": list(SHARED_CONSUMERS),
        "status": "ready",
        "closed_loop": "canonical_explicit_host->profile_sync->action_queue->capability_lease->senju_trial_space",
    }


def _unknown_cases(state: Path, explicit_hosts: set[str], *, now: int) -> list[dict[str, Any]]:
    doc = _load_json(state / "discovery_candidates.json", {})
    rows = doc.get("candidates", ()) if isinstance(doc, Mapping) else ()
    if not isinstance(rows, list):
        return []
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("decision") or "") not in {"candidate_only", "review_required"}:
            continue
        try:
            host = _normalize_host(str(raw.get("host") or ""))
        except ValueError:
            continue
        if host in explicit_hosts or host in seen:
            continue
        seen.add(host)
        cases.append(
            {
                "host": host,
                "url": str(raw.get("url") or f"https://{host}/"),
                "current_stage": "awaiting_explicit_owner_authorization",
                "blocking_reason": "canonical_explicit_owner_authorization_missing",
                "next_action": "META_prepare_single_PR_host_activation_bundle_and_collect_host_attestation",
                "approval_coordinator": "META",
                "recommendation_or_discovery_is_authority": False,
                "transport_enabled": False,
                "credential_scope": "none",
                "single_pr_completion_target": [
                    "canonical_authorization",
                    "authorized_target",
                    "senju_trial_profile",
                ],
                "first_seen_at": int(raw.get("discovered_at", now) or now),
                "last_progress_at": now,
            }
        )
    cases.sort(key=lambda row: row["host"])
    return cases


def sync_new_host_authorizations(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> dict[str, Any]:
    """Activate every newly canonical explicit exact host into the current live queue."""
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    ttl = max(300, min(int(ttl_seconds), MAX_TTL_SECONDS))

    targets = _canonical_explicit_targets(root)
    policy = _load_json(state / "discovery_policy.json", {})
    if not isinstance(policy, dict):
        policy = {}
    profiles = policy.get("action_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    else:
        profiles = dict(profiles)

    queue_doc = _load_json(state / "discovery_action_queue.json", {})
    existing_actions = queue_doc.get("actions", ()) if isinstance(queue_doc, Mapping) else ()
    if not isinstance(existing_actions, list):
        existing_actions = []
    actions_by_host: dict[str, dict[str, Any]] = {}
    unrelated_actions: list[dict[str, Any]] = []
    for raw in existing_actions:
        if not isinstance(raw, dict):
            continue
        try:
            host = _normalize_host(str(raw.get("target") or ""))
        except ValueError:
            unrelated_actions.append(dict(raw))
            continue
        actions_by_host[host] = dict(raw)

    activated: list[dict[str, Any]] = []
    profile_created = 0
    profile_updated = 0
    senju_trial_ready_count = 0
    for host, target in sorted(targets.items()):
        existing_profile = profiles.get(host)
        profile = _profile_for_target(target, existing_profile if isinstance(existing_profile, Mapping) else None)
        if profile is None:
            continue
        if existing_profile is None:
            profile_created += 1
        elif dict(existing_profile) != profile:
            profile_updated += 1
        profiles[host] = profile
        action = _action_row(target, profile, now=current, ttl_seconds=ttl)
        actions_by_host[host] = action
        senju = _senju_trial_summary(profile)
        if senju["ready"]:
            senju_trial_ready_count += 1
        activated.append(
            {
                "host": host,
                "authorization_reference": action["authorization_reference"],
                "capabilities": action["capabilities"],
                "credential_scope": action["credential_scope"],
                "action_queue_ready": True,
                "exact_host_only": True,
                "senju_trial_ready": senju["ready"],
                "senju_trial_methods": senju["methods"],
                "senju_trial_paths": senju["paths"],
                "senju_max_actions_per_cycle": senju["max_actions_per_cycle"],
            }
        )

    policy["action_profiles"] = profiles
    policy["new_host_authorization"] = {
        "mode": "canonical_explicit_exact_host_auto_activation",
        "pr_contract": "single_PR_authorization_allowlist_senju_trial_profile",
        "same_cycle_action_queue": True,
        "same_cycle_capability_lease": True,
        "discovery_only_may_authorize": False,
        "recommendation_only_may_authorize": False,
        "external_link_inheritance_used": False,
        "cross_host_credential_inheritance": False,
    }
    _write_json(state / "discovery_policy.json", policy)

    merged_actions = unrelated_actions + list(actions_by_host.values())
    merged_actions.sort(key=lambda row: str(row.get("target") or ""))
    _write_json(
        state / "discovery_action_queue.json",
        {
            "schema": ACTION_QUEUE_SCHEMA,
            "generated_at": current,
            "mode": "live_queue_plus_canonical_explicit_new_host_activation",
            "actions": merged_actions,
        },
    )

    cases = _unknown_cases(state, set(targets), now=current)
    _write_json(
        state / "new_host_authorization_cases.json",
        {
            "schema": CASE_SCHEMA,
            "generated_at": current,
            "cases": cases,
            "case_count": len(cases),
            "unknown_host_transport_enabled": False,
        },
    )

    result = {
        "schema": ACTIVATION_SCHEMA,
        "generated_at": current,
        "canonical_explicit_host_count": len(targets),
        "activated_host_count": len(activated),
        "new_profiles_created": profile_created,
        "profiles_narrowed_or_refreshed": profile_updated,
        "senju_trial_ready_count": senju_trial_ready_count,
        "review_case_count": len(cases),
        "same_cycle_action_queue": True,
        "same_cycle_capability_lease_ready": True,
        "single_pr_completion_contract": True,
        "unknown_host_auto_authorization": False,
        "external_link_inheritance_used": False,
        "cross_host_credential_inheritance": False,
        "activations": activated,
    }
    _write_json(state / "new_host_authorization_activation.json", result)
    return result
