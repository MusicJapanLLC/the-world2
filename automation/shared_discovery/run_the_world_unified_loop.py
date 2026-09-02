#!/usr/bin/env python3
"""CLI for the unified authorized The world production loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.production_state_bootstrap import bootstrap_owner_runtime_state
from engine.the_world_unified_loop import run_the_world_unified_loop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".the-world-runtime")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--tuning-state")
    parser.add_argument("--require-credentialed-write", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    state = Path(args.state)
    repo_root = Path(args.repo_root)
    runtime_bootstrap = bootstrap_owner_runtime_state(state, repo_root=repo_root)
    result = run_the_world_unified_loop(
        state,
        repo_root=repo_root,
        tuning_state_path=args.tuning_state,
        require_credentialed_write=args.require_credentialed_write,
    )
    result["runtime_bootstrap"] = runtime_bootstrap

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
