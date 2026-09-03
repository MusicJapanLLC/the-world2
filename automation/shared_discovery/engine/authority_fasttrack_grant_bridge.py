"""Bridge 5% authority-transition fast-track requests into real reviewed grants.

A fast-track hit is only a trigger.  Authority is emitted only when the exact candidate
host is independently covered by a currently explicit Owner root from canonical trusted
configuration.  Eligible candidates receive the same short-lived, read-only grant shape
used by the independent authority reviewer and are written to
``authority_reviewed_grants.json`` -- the live grant file consumed by the existing
Discovery/Execution authority pipeline.

This creates a real operational Authority path for newly discovered exact hosts inside an
already explicit Owner root while keeping unrelated third-party roots, terminal stops,
credentials, mutation methods, and HARD_DENY identity bypass out of this bridge.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .authority_reviewer import (
    DEFAULT_TTL_SECONDS,
    _covered_by_root,
    _explicit_roots,
    _host_from_url,
    _load_json,
    _normalize_host,
)

SCHEMA = "the-world-fasttrack-reviewed-authority-grants/v1"
REVIEWED_GRANT_SCHEMA = "meta-authority-reviewed-grants/v1"
SHARED_WITH = ("META", "X", "SENJU", "CHILD", "PR-ARMY", "AI")


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _active_prior_grants(state: Path, roots: set[str], *, now: int) -> dict[str, dict[str, Any]]:
    prior = _load_json(state / "authority_reviewed_grants.json", {})
    hosts = prior.get("hosts", {}) if isinstance(prior, Mapping) else {}
    active: dict[str, dict[str, Any]] = {}
    for raw_host, raw_grant in hosts.items() if isinstance(hosts, Mapping) else ():
        if not isinstance(raw_grant, Mapping):
            continue
        host = _normalize_host(str(raw_host))
        if not host:
            continue
        try:
            expiry = int(raw_grant.get("expires_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        if expiry <= now:
            continue
        if _covered_by_root(host, roots) is None:
            continue
        active[host] = dict(raw_grant)
    return active


def run_fasttrack_grant_bridge(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> dict[str, Any]:
    """Issue real reviewed grants for eligible fast-tracked exact hosts."""
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    ttl = max(300, min(int(ttl_seconds), 24 * 60 * 60))

    queue = _load_json(state / "authority_priority_review_queue.json", {})
    requests = queue.get("requests", []) if isinstance(queue, Mapping) else []
    if not isinstance(requests, list):
        requests = []

    explicit_roots = _explicit_roots(root)
    grants = _active_prior_grants(state, explicit_roots, now=current)
    issued: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []

    for raw in requests:
        if not isinstance(raw, Mapping) or raw.get("authority_transition_requested") is not True:
            continue
        host = _normalize_host(str(raw.get("host", "")))
        url = str(raw.get("url", ""))
        if not host or _host_from_url(url) != host:
            held.append({"host": raw.get("host"), "url": url, "reason": "invalid_https_candidate"})
            continue

        matched_root = _covered_by_root(host, explicit_roots)
        if matched_root is None:
            held.append({
                "host": host,
                "url": url,
                "reason": "no_independent_explicit_owner_root",
            })
            continue

        grant = {
            "host": host,
            "matched_explicit_root": matched_root,
            "reviewer": "fasttrack-authority-grant-bridge/v1",
            "grant_source": "five_percent_fasttrack_plus_independent_owner_root",
            "reviewed_at": current,
            "expires_at": current + ttl,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "effect": "read_only",
            "allow_http": False,
            "allow_delete": False,
            "redirect_eligible": True,
            "shared_with": list(SHARED_WITH),
        }
        grants[host] = grant
        issued.append({
            "host": host,
            "url": url,
            "matched_explicit_root": matched_root,
            "expires_at": current + ttl,
            "authority_effect": "real_reviewed_operational_grant",
            "shared_with": list(SHARED_WITH),
        })

    reviewed_doc = {
        "schema": REVIEWED_GRANT_SCHEMA,
        "generated_at": current,
        "mode": "independent_probationary_read_only_plus_fasttrack_bridge",
        "hosts": dict(sorted(grants.items())),
    }
    _write(state / "authority_reviewed_grants.json", reviewed_doc)

    shared_doc = {
        "schema": SCHEMA,
        "generated_at": current,
        "authority_source": "explicit_owner_root_independent_recheck",
        "fasttrack_is_trigger_not_authority": True,
        "shared_with": list(SHARED_WITH),
        "issued_count": len(issued),
        "held_count": len(held),
        "issued": issued,
        "held": held,
        "new_unrelated_root_self_mint": False,
        "hard_deny_identity_bypass": False,
        "credential_mint": False,
    }
    _write(state / "authority_fasttrack_issued_grants.json", shared_doc)
    return shared_doc
