#!/usr/bin/env python3
"""Plan discovery-derived external actions without executing network I/O.

The planner applies the same lease/profile/canonical-target/method checks as the real
executor, but only materializes an inspectable candidate queue. It intentionally does
not call ExternalContactClient or perform any external request.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from engine.discovery_action_failover import _canonical_explicit_target, _method_allowed
from engine.discovery_capability_leases import load_discovery_capability_leases
from engine.discovery_external_action import _action_rows, _profile

MAX_PLANNED_CANDIDATES = 300


def build_plan(state_dir: str | Path, *, repo_root: str | Path, max_candidates: int = 300) -> dict:
    state = Path(state_dir)
    root = Path(repo_root)
    limit = max(1, min(int(max_candidates), MAX_PLANNED_CANDIDATES))
    candidates: list[dict] = []
    denied = 0

    for lease in load_discovery_capability_leases(state):
        if len(candidates) >= limit:
            break
        if not lease.is_active():
            continue
        target = _canonical_explicit_target(root, lease.target)
        profile = _profile(state, lease.target)
        if target is None or profile is None:
            continue
        for capability in ("write", "mutation"):
            if len(candidates) >= limit:
                break
            if capability not in lease.capabilities:
                continue
            for action in _action_rows(profile, capability):
                if len(candidates) >= limit:
                    break
                method = action["method"]
                if not _method_allowed(target, method):
                    denied += 1
                    continue
                candidates.append(
                    {
                        "target": lease.target,
                        "capability": capability,
                        "action_id": action["id"],
                        "method": method,
                        "path": action["path"],
                        "authorization_reference": lease.authorization_reference,
                        "credential_scope": lease.credential_scope,
                    }
                )

    return {
        "schema": "meta-discovery-external-action-plan/v1",
        "generated_at": int(time.time()),
        "max_candidates": limit,
        "candidate_count": len(candidates),
        "denied_before_plan": denied,
        "network_io_attempted": False,
        "authority_minted": False,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--max-candidates", type=int, default=300)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = build_plan(args.state, repo_root=args.repo_root, max_candidates=args.max_candidates)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("max_candidates", "candidate_count", "network_io_attempted")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
