#!/usr/bin/env python3
"""Execute durable replica leases through Senju's authorized real network lane.

Replica execution never expands authority. It consumes only unexpired logical replicas
whose exact host is already present in the active runtime policy, performs an HTTPS GET,
and emits response links as evidence for the next policy pass.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from senju.external import ExternalContactClient, ExternalContactPolicy
from network_policy_authorized_discovery import _extract_links


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _active_hosts(policy: dict[str, Any], now: int) -> set[str]:
    grants = policy.get("grants", {}) if isinstance(policy, dict) else {}
    out: set[str] = set()
    if not isinstance(grants, dict):
        return out
    for raw_host, grant in grants.items():
        if not isinstance(grant, dict):
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
        host = str(raw_host).lower().rstrip(".")
        if host:
            out.add(host)
    return out


def _valid_replica_rows(doc: dict[str, Any], active_hosts: set[str], now: int) -> list[dict[str, Any]]:
    rows = doc.get("replicas", []) if isinstance(doc, dict) else []
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("lease_expires_at", 0)) <= now:
            continue
        if str(row.get("effect")) != "read_only_network_contact":
            continue
        if str(row.get("credential_scope", "none")) != "none":
            continue
        methods = {str(x).upper() for x in row.get("allowed_methods", [])}
        if "GET" not in methods:
            continue
        raw_url = row.get("url")
        if not isinstance(raw_url, str):
            continue
        try:
            parsed = urllib.parse.urlsplit(raw_url)
            port = parsed.port
        except ValueError:
            continue
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https" or not host or host not in active_hosts:
            continue
        if parsed.username is not None or parsed.password is not None or port not in (None, 443):
            continue
        out.append({**row, "host": host})
    out.sort(key=lambda row: (str(row.get("host")), str(row.get("url")), str(row.get("id"))))
    return out


def apply_replicas(
    policy: dict[str, Any],
    replicas: dict[str, Any],
    *,
    now: int | None = None,
    max_actions: int = 32,
    client_factory: Callable[[ExternalContactPolicy], ExternalContactClient] | None = None,
) -> dict[str, Any]:
    now = int(time.time()) if now is None else int(now)
    max_actions = max(0, min(int(max_actions), 64))
    active_hosts = _active_hosts(policy, now)
    rows = _valid_replica_rows(replicas, active_hosts, now)[:max_actions]
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    if rows:
        contact_policy = ExternalContactPolicy.from_hosts(
            sorted(active_hosts),
            allow_http=False,
            allow_delete=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=7.5,
            max_response_bytes=256 * 1024,
            retries=1,
        )
        client = client_factory(contact_policy) if client_factory else ExternalContactClient(contact_policy)
        for row in rows:
            url = str(row["url"])
            host = str(row["host"])
            try:
                result = client.contact_with_body(url, method="GET")
                links = _extract_links(result.receipt.final_url, result.text(), result.receipt.content_type)
                success = bool(result.receipt.provider_acknowledged)
                results.append(
                    {
                        "replica_id": row.get("id"),
                        "generation": row.get("generation"),
                        "host": host,
                        "url": url,
                        "success": success,
                        "status": result.receipt.status,
                        "final_url": result.receipt.final_url,
                        "discovered_links": len(links),
                    }
                )
                for link in links:
                    try:
                        parsed = urllib.parse.urlsplit(link)
                    except ValueError:
                        continue
                    findings.append(
                        {
                            "url": link,
                            "host": (parsed.hostname or "").lower().rstrip("."),
                            "source": f"persistent_replica:{row.get('id')}",
                            "finding": "host_or_endpoint_discovered_from_persistent_replica",
                        }
                    )
            except Exception as exc:
                results.append(
                    {
                        "replica_id": row.get("id"),
                        "generation": row.get("generation"),
                        "host": host,
                        "url": url,
                        "success": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )

    discovered_urls = sorted({str(row["url"]) for row in findings if row.get("url")})
    return {
        "schema": "meta-network-persistent-replica-evidence/v1",
        "production": True,
        "closed_loop": True,
        "generated_at": now,
        "source": "persistent_authorized_replica_external_action",
        "attempted": len(results),
        "succeeded": sum(1 for row in results if row.get("success")),
        "failed": sum(1 for row in results if not row.get("success")),
        "results": results,
        "findings": findings,
        "discovered_urls": discovered_urls,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="automation/codegen/meta_state/network_policy_runtime.json")
    ap.add_argument("--replicas", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-actions", type=int, default=32)
    args = ap.parse_args()

    result = apply_replicas(
        _load(Path(args.policy)),
        _load(Path(args.replicas)),
        max_actions=args.max_actions,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "attempted": result["attempted"],
                "succeeded": result["succeeded"],
                "failed": result["failed"],
                "discovered_urls": len(result["discovered_urls"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
