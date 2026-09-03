#!/usr/bin/env python3
"""Run persistent learning + same-authority failover for discovery external actions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.discovery_action_failover import run_discovery_action_failover
from engine.discovery_capability_leases import issue_discovery_capability_leases
from engine.discovery_replica_continuity import rebuild_discovery_capability_replicas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--max-actions", type=int, default=8)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)

    failover = run_discovery_action_failover(
        state,
        repo_root=args.repo_root,
        max_actions=args.max_actions,
    )
    # Rebuild operational state from the current live queue after retry. This closes the
    # persistence/recovery edge without letting failover receipts become an authority root.
    leases = issue_discovery_capability_leases(state)
    replicas = rebuild_discovery_capability_replicas(state)

    payload = {
        "schema": "meta-discovery-action-failover-run/v1",
        "closed_loop": True,
        "rule": "failure->learn->alternate_transport_same_authority->retry->rebuild",
        "failover": failover,
        "leases": leases,
        "replicas": replicas,
        "authority_invariant": "same_live_exact_target_authority_only",
        "boundary_denial_bypass": False,
    }
    destination = Path(args.json_out) if args.json_out else state / "discovery_action_failover_run.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
