"""Production contract for maximum automatic authority inside an existing owner envelope.

This module does not mint a new authority root. It verifies that discovery which is
already covered by explicit owner policy actually reaches the operational fast path:

    discovery -> authorized -> action queue

Unknown unrelated hosts remain outside the contract and cannot gain authority merely by
being discovered. The purpose of this module is to make the owner-authorized path
fail-loud instead of silently degrading back to a candidate-only state.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host

CONTRACT_SCHEMA = "meta-discovery-authority-contract/v1"
EXECUTABLE_CAPABILITIES = frozenset({"scan", "probe", "write", "mutation", "credentialed_action"})


class DiscoveryAuthorityContractError(RuntimeError):
    """Raised when owner-authorized discovery falls out of the automatic authority path."""


def _within_owner_root(host: str, roots: tuple[str, ...]) -> str | None:
    for root in roots:
        if host == root or host.endswith("." + root):
            return root
    return None


def _policy_roots(policy: Mapping[str, Any]) -> tuple[str, ...]:
    roots: set[str] = set()
    for value in policy.get("trusted_roots", []):
        try:
            roots.add(_normalize_host(str(value)))
        except ValueError:
            continue
    for value in policy.get("company_domains", []):
        try:
            roots.add(_normalize_host(str(value)))
        except ValueError:
            continue
    return tuple(sorted(roots, key=lambda item: (-len(item), item)))


def _authorized_hosts(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "discovery_authorized.json", {})
    raw = doc.get("hosts", {}) if isinstance(doc, Mapping) else {}
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(raw, Mapping):
        return result
    for host, grant in raw.items():
        if not isinstance(grant, Mapping):
            continue
        try:
            result[_normalize_host(str(host))] = grant
        except ValueError:
            continue
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
        try:
            host = _normalize_host(str(row.get("target", "")))
        except ValueError:
            continue
        result[host] = row
    return result


def _explicit_profile_capabilities(policy: Mapping[str, Any], host: str) -> frozenset[str]:
    profiles = policy.get("action_profiles", {})
    if not isinstance(profiles, Mapping):
        return frozenset()
    raw = profiles.get(host)
    if not isinstance(raw, Mapping):
        return frozenset()
    if str(raw.get("owner_authorization", "")).strip().lower() != "explicit":
        return frozenset()
    return frozenset(
        str(item).strip().lower()
        for item in raw.get("capabilities", [])
        if str(item).strip().lower() in EXECUTABLE_CAPABILITIES
    )


def enforce_discovery_authority_contract(
    state_dir: str | Path,
    *,
    receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Fail if an owner-envelope discovery is left behind as a non-authorized candidate.

    The contract deliberately checks only authority already established by owner policy.
    It never promotes an unrelated host, never creates credentials, and never changes a
    target after failure.
    """
    state = Path(state_dir)
    policy = _load_json(state / "discovery_policy.json", {})
    if not isinstance(policy, Mapping):
        raise DiscoveryAuthorityContractError("discovery policy is missing or malformed")

    roots = _policy_roots(policy)
    if not roots:
        raise DiscoveryAuthorityContractError("no explicit owner discovery roots configured")

    authorized = _authorized_hosts(state)
    actions = _ready_actions(state)
    candidates_doc = _load_json(state / "discovery_candidates.json", {})
    candidate_rows = candidates_doc.get("candidates", []) if isinstance(candidates_doc, Mapping) else []
    shared_doc = _load_json(state / "shared_discovery_knowledge.json", {})
    shared_rows = shared_doc.get("discoveries", []) if isinstance(shared_doc, Mapping) else []

    violations: list[str] = []
    owner_discovery_hosts: set[str] = set()
    owner_discovery_urls = 0

    for row in candidate_rows if isinstance(candidate_rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        try:
            host = _normalize_host(str(row.get("host", "")))
        except ValueError:
            continue
        root = _within_owner_root(host, roots)
        if root is None:
            continue
        owner_discovery_hosts.add(host)
        owner_discovery_urls += 1
        decision = str(row.get("decision", ""))
        if decision != "probationary_authorized":
            violations.append(f"owner-envelope discovery {host} has decision={decision!r}")
        if host not in authorized:
            violations.append(f"owner-envelope discovery {host} has no live discovery grant")
        if host not in actions:
            violations.append(f"owner-envelope discovery {host} has no ready action-queue entry")

    for row in shared_rows if isinstance(shared_rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        try:
            host = _normalize_host(str(row.get("host", "")))
        except ValueError:
            continue
        if _within_owner_root(host, roots) is None:
            continue
        if str(row.get("decision", "")) != "probationary_authorized":
            violations.append(f"shared owner-envelope discovery {host} is not authorized")

    # Exact explicit owner profiles are the high-impact authority ceiling. If an exact
    # profiled host is discovered, its ready action row must carry every declared
    # executable capability. Descendant inheritance is intentionally not inferred here.
    for host in sorted(owner_discovery_hosts):
        declared = _explicit_profile_capabilities(policy, host)
        if not declared:
            continue
        row = actions.get(host)
        if row is None:
            continue
        actual = {
            str(item).strip().lower()
            for item in row.get("capabilities", [])
            if str(item).strip().lower() in EXECUTABLE_CAPABILITIES
        }
        missing = declared - actual
        if missing:
            violations.append(
                f"explicit owner profile {host} lost capabilities: {','.join(sorted(missing))}"
            )

    # Outside discoveries may still exist for review, but they must not silently appear
    # as action-ready unless some independent explicit authorization source promoted them.
    outside_review_count = 0
    for row in candidate_rows if isinstance(candidate_rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        try:
            host = _normalize_host(str(row.get("host", "")))
        except ValueError:
            continue
        if _within_owner_root(host, roots) is not None:
            continue
        if str(row.get("decision", "")) == "candidate_only":
            outside_review_count += 1
            if host in actions and host not in authorized:
                violations.append(f"ungranted outside host {host} reached action queue")

    receipt = {
        "schema": CONTRACT_SCHEMA,
        "generated_at": int(time.time()),
        "status": "pass" if not violations else "fail",
        "owner_roots": list(roots),
        "owner_discovery_host_count": len(owner_discovery_hosts),
        "owner_discovery_url_count": owner_discovery_urls,
        "owner_candidate_only_count": sum(
            1
            for row in candidate_rows if isinstance(candidate_rows, list) and isinstance(row, Mapping)
            and str(row.get("decision", "")) == "candidate_only"
            and _safe_within_owner(str(row.get("host", "")), roots)
        ),
        "outside_review_count": outside_review_count,
        "authorized_host_count": len(authorized),
        "ready_action_host_count": len(actions),
        "violations": violations,
        "contract": "owner-envelope discovery must be authorized and action-ready in the same cycle",
        "new_authority_roots_from_discovery": False,
    }
    destination = Path(receipt_path) if receipt_path is not None else state / "discovery_authority_contract.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if violations:
        raise DiscoveryAuthorityContractError("; ".join(violations))
    return receipt


def _safe_within_owner(raw_host: str, roots: tuple[str, ...]) -> bool:
    try:
        host = _normalize_host(raw_host)
    except ValueError:
        return False
    return _within_owner_root(host, roots) is not None
