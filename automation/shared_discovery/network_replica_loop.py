#!/usr/bin/env python3
"""Build durable logical replicas from already-authorized network discoveries.

A replica is a restartable unit of work, not a new authority grant. Replica leases are
created only for HTTPS URLs whose exact host already has an active runtime grant. The
result is designed to be persisted as a GitHub Actions artifact and restored by the next
production cycle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any


def _load(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _normalize_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = urllib.parse.urlsplit(raw.strip())
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port not in (None, 443):
        return None
    host = parsed.hostname.lower().rstrip(".")
    return urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _active_grants(policy: dict[str, Any], now: int) -> dict[str, dict[str, Any]]:
    rows = policy.get("grants", {}) if isinstance(policy, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, dict):
        return out
    for raw_host, grant in rows.items():
        if not isinstance(grant, dict):
            continue
        host = str(raw_host).lower().rstrip(".")
        if not host:
            continue
        if int(grant.get("expires_at", 0)) <= now:
            continue
        if str(grant.get("credential_scope", "none")) != "none":
            continue
        if str(grant.get("effect", "read_only_network_contact")) != "read_only_network_contact":
            continue
        methods = {str(x).upper() for x in grant.get("allowed_methods", [])}
        if "GET" not in methods:
            continue
        out[host] = grant
    return out


def _discovered_urls(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("discovered_urls", []) if isinstance(doc, dict) else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        url = _normalize_url(item)
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _previous_replicas(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("replicas", []) if isinstance(doc, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _host_for(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def build_replicas(
    policy: dict[str, Any],
    discovery: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    now: int | None = None,
    lease_seconds: int = 43200,
    max_replicas: int = 64,
) -> dict[str, Any]:
    now = int(time.time()) if now is None else int(now)
    lease_seconds = max(300, min(int(lease_seconds), 24 * 3600))
    max_replicas = max(0, min(int(max_replicas), 96))
    grants = _active_grants(policy, now)

    previous = previous or {}
    previous_by_url: dict[str, dict[str, Any]] = {}
    for row in _previous_replicas(previous):
        url = _normalize_url(row.get("url"))
        if not url:
            continue
        host = _host_for(url)
        if host not in grants:
            continue
        if int(row.get("lease_expires_at", 0)) <= now:
            continue
        previous_by_url[url] = row

    candidates: list[str] = list(previous_by_url)
    for url in _discovered_urls(discovery):
        if url not in previous_by_url:
            candidates.append(url)

    # Keep the persistence half of the loop alive even when an authorized response has
    # no internal links. If no carried/discovered URL is already inside active authority,
    # seed canonical URLs from the active grants themselves. This reuses existing
    # authority; it does not mint or widen a grant.
    if grants and not any(_host_for(url) in grants for url in candidates):
        for host, grant in sorted(grants.items()):
            grant_url = _normalize_url(grant.get("url")) or f"https://{host}/"
            if grant_url not in candidates:
                candidates.append(grant_url)

    replicas: list[dict[str, Any]] = []
    held = 0
    seen: set[str] = set()
    for url in candidates:
        if len(replicas) >= max_replicas:
            break
        if url in seen:
            continue
        seen.add(url)
        host = _host_for(url)
        grant = grants.get(host)
        if grant is None:
            held += 1
            continue
        prior = previous_by_url.get(url, {})
        replica_id = str(prior.get("id") or f"net-replica-{hashlib.sha256(url.encode()).hexdigest()[:12]}")
        generation = max(0, int(prior.get("generation", 0))) + 1
        lease_expires_at = min(int(grant.get("expires_at", now + lease_seconds)), now + lease_seconds)
        replicas.append(
            {
                "id": replica_id,
                "generation": generation,
                "host": host,
                "url": url,
                "created_or_refreshed_at": now,
                "lease_expires_at": lease_expires_at,
                "effect": "read_only_network_contact",
                "allowed_methods": ["GET"],
                "credential_scope": "none",
                "authorization_basis": grant.get("authorization_basis"),
                "authorization_reference": grant.get("authorization_reference"),
                "persistence_backend": "github_actions_artifact",
                "next_action": "authorized_get",
            }
        )

    return {
        "schema": "meta-network-persistent-replicas/v1",
        "production": True,
        "closed_loop": True,
        "generated_at": now,
        "persistence_backend": "github_actions_artifact",
        "authority_expansion": "existing_runtime_grants_only",
        "replica_count": len(replicas),
        "held_outside_active_authority": held,
        "replicas": replicas,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="automation/codegen/meta_state/network_policy_runtime.json")
    ap.add_argument("--discovery", required=True)
    ap.add_argument("--previous")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lease-seconds", type=int, default=43200)
    ap.add_argument("--max-replicas", type=int, default=64)
    args = ap.parse_args()

    result = build_replicas(
        _load(Path(args.policy)),
        _load(Path(args.discovery)),
        previous=_load(Path(args.previous)) if args.previous else {},
        lease_seconds=args.lease_seconds,
        max_replicas=args.max_replicas,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "replica_count": result["replica_count"],
                "held_outside_active_authority": result["held_outside_active_authority"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
