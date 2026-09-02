#!/usr/bin/env python3
"""Run one META/X closed-loop descendant cycle.

Example:
    PYTHONPATH=senju python senju/scripts/run_meta_x_closed_loop.py \
      --system META --parent-id META-CHILD-01 --generation 1 \
      --desired-count 100 --scope read:state --scope write:state

The runner persists pending descendants and shared non-secret state under senju/state.
Re-running the command resumes deferred descendants as capacity becomes available.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from senju.meta.closed_loop_agent_fabric import (
    queue_descendant_request,
    run_closed_loop_cycle,
)
from senju.meta.recursive_agent_broker import MAX_ACTIVE_AGENTS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default="senju/state")
    parser.add_argument("--system", choices=("META", "X"), required=True)
    parser.add_argument("--parent-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--desired-count", type=int, default=10)
    parser.add_argument("--scope", action="append", dest="scopes", required=True)
    parser.add_argument("--narrow-scope", action="append", dest="narrow_scopes")
    parser.add_argument("--active-agents", type=int, default=0)
    parser.add_argument("--active-limit", type=int, default=MAX_ACTIVE_AGENTS)
    parser.add_argument("--resume-only", action="store_true")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if not args.resume_only:
        queue_descendant_request(
            state_dir=state_dir,
            system=args.system,
            parent_id=args.parent_id,
            parent_generation=args.generation,
            parent_scopes=args.scopes,
            requested_scopes=args.narrow_scopes,
            desired_count=args.desired_count,
        )

    result = run_closed_loop_cycle(
        state_dir=state_dir,
        active_agents=args.active_agents,
        active_limit=args.active_limit,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
