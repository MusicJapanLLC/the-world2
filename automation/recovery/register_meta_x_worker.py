"""Build one durable META/X recovery-worker registration.

The registration is only valid inside an owner-approved namespace from
approved_persistence_registry.json. No arbitrary code, URL, webhook endpoint, startup
command, provider, repository, workflow, or ref can be introduced by META/X.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation.recovery.approved_persistence import DEFAULT_REGISTRY, _load_json, validate_dynamic_worker


def build_registration(
    *,
    actor: str,
    namespace_id: str,
    worker_id: str,
    role: str,
    workflow: str,
    ref: str,
    heartbeat_file: str,
    heartbeat_field: str,
    stale_after_seconds: int,
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict:
    registry = _load_json(Path(registry_path))
    namespaces = {
        row.get("id"): row
        for row in registry.get("owner_approved_namespaces", [])
        if isinstance(row, dict) and row.get("owner_authorized") is True
    }
    namespace = namespaces.get(namespace_id)
    if not isinstance(namespace, dict):
        raise PermissionError("owner-approved namespace not found")

    worker = {
        "schema": "the-world-meta-x-dynamic-worker/v1",
        "id": worker_id,
        "actor": actor.upper(),
        "meta_x_approved": True,
        "namespace_id": namespace_id,
        "provider": namespace.get("provider"),
        "repository": namespace.get("repository"),
        "role": role,
        "heartbeat_file": heartbeat_file,
        "heartbeat_field": heartbeat_field,
        "stale_after_seconds": max(60, min(int(stale_after_seconds), 7 * 24 * 3600)),
        "recovery": {
            "kind": "workflow_dispatch",
            "workflow": workflow,
            "ref": ref,
        },
    }
    valid, reason = validate_dynamic_worker(worker, registry)
    if not valid:
        raise PermissionError(reason)
    return worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Create validated META/X recovery-worker registration")
    parser.add_argument("--actor", required=True, choices=["META", "X"])
    parser.add_argument("--namespace-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--heartbeat-file", required=True)
    parser.add_argument("--heartbeat-field", default="alive_at")
    parser.add_argument("--stale-after-seconds", type=int, default=7200)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--out")
    args = parser.parse_args()

    worker = build_registration(
        actor=args.actor,
        namespace_id=args.namespace_id,
        worker_id=args.worker_id,
        role=args.role,
        workflow=args.workflow,
        ref=args.ref,
        heartbeat_file=args.heartbeat_file,
        heartbeat_field=args.heartbeat_field,
        stale_after_seconds=args.stale_after_seconds,
        registry_path=args.registry,
    )
    text = json.dumps(worker, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
