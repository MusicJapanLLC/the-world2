#!/usr/bin/env python3
"""Apply the generated runtime network policy through Senju's real contact client.

Only active read-only runtime grants are consumed. Active grants share one exact-host
contact policy, so redirects are allowed between hosts that are already present in the
same runtime allowlist. Each host is tried with HEAD first and GET as a bounded fallback;
the first acknowledged response is success. Results become feedback for the next policy
cycle.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

from senju.external import ExternalContactClient, ExternalContactPolicy


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _active_grants(doc: dict[str, Any], now: int) -> list[dict[str, Any]]:
    grants = doc.get("grants", {}) if isinstance(doc, dict) else {}
    active: list[dict[str, Any]] = []
    if not isinstance(grants, dict):
        return active
    for host, grant in grants.items():
        if not isinstance(grant, dict):
            continue
        if int(grant.get("expires_at", 0)) <= now:
            continue
        if str(grant.get("credential_scope", "none")) != "none":
            continue
        if str(grant.get("effect", "read_only_network_contact")) != "read_only_network_contact":
            continue
        methods = {str(x).upper() for x in grant.get("allowed_methods", [])}
        if not methods.intersection({"HEAD", "GET"}):
            continue
        active.append({**grant, "host": str(host), "_methods": methods})
    active.sort(key=lambda row: row["host"])
    return active


def apply_runtime_policy(
    doc: dict[str, Any],
    *,
    max_hosts: int = 32,
    client_factory: Callable[[ExternalContactPolicy], ExternalContactClient] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    active = _active_grants(doc, now)[: max(0, min(int(max_hosts), 96))]
    allowed_hosts = sorted({row["host"] for row in active})
    results: list[dict[str, Any]] = []

    if allowed_hosts:
        contact_policy = ExternalContactPolicy.from_hosts(
            allowed_hosts,
            allow_http=False,
            allow_delete=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=7.5,
            max_response_bytes=256 * 1024,
            retries=1,
        )
        client = client_factory(contact_policy) if client_factory else ExternalContactClient(contact_policy)

        for grant in active:
            host = grant["host"]
            url = str(grant.get("url") or f"https://{host}/")
            methods = grant.get("_methods", set())
            method_order = [m for m in ("HEAD", "GET") if m in methods]
            attempts: list[dict[str, Any]] = []
            success_row: dict[str, Any] | None = None

            for method in method_order:
                try:
                    receipt = client.contact(url, method=method)
                    attempt = {
                        "method": method,
                        "success": bool(receipt.provider_acknowledged),
                        "status": receipt.status,
                        "final_url": receipt.final_url,
                        "contacted_hosts": list(receipt.contacted_hosts),
                    }
                    attempts.append(attempt)
                    if receipt.provider_acknowledged:
                        success_row = attempt
                        break
                except Exception as exc:
                    attempts.append(
                        {
                            "method": method,
                            "success": False,
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                    )

            chosen = success_row or (attempts[-1] if attempts else {"success": False})
            results.append(
                {
                    "host": host,
                    "url": url,
                    "success": bool(success_row),
                    "method": chosen.get("method"),
                    "status": chosen.get("status"),
                    "final_url": chosen.get("final_url"),
                    "contacted_hosts": chosen.get("contacted_hosts", []),
                    "attempts": attempts,
                    "authorization_basis": grant.get("authorization_basis"),
                    "authorization_reference": grant.get("authorization_reference"),
                }
            )

    return {
        "schema": "meta-network-policy-apply-audit/v2",
        "production": True,
        "closed_loop": True,
        "generated_at": now,
        "policy_hash": doc.get("policy_hash"),
        "allowed_hosts": allowed_hosts,
        "attempted": len(results),
        "request_attempts": sum(len(row.get("attempts", [])) for row in results),
        "succeeded": sum(1 for row in results if row.get("success")),
        "failed": sum(1 for row in results if not row.get("success")),
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="automation/codegen/meta_state/network_policy_runtime.json")
    ap.add_argument("--out", default="automation/codegen/meta_state/network_policy_apply_audit.json")
    ap.add_argument("--feedback", default="automation/codegen/meta_state/network_policy_feedback.json")
    ap.add_argument("--max-hosts", type=int, default=32)
    args = ap.parse_args()

    policy_path = Path(args.policy)
    doc = _load(policy_path)
    audit = apply_runtime_policy(doc, max_hosts=args.max_hosts)
    feedback = {
        "schema": "meta-network-policy-feedback/v2",
        "generated_at": audit["generated_at"],
        "source": "runtime_network_policy_apply",
        "findings": [
            {
                "host": row["host"],
                "url": row["url"],
                "success": bool(row.get("success")),
                "method": row.get("method"),
                "status": row.get("status"),
                "finding": "network_policy_apply_result",
            }
            for row in audit["results"]
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    feedback_path = Path(args.feedback)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "attempted": audit["attempted"],
                "request_attempts": audit["request_attempts"],
                "succeeded": audit["succeeded"],
                "failed": audit["failed"],
                "policy_hash": audit["policy_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
