#!/usr/bin/env python3
"""CLI for autonomous authority opportunity exploration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.authority_opportunity_explorer import run_authority_opportunity_explorer
from engine.production_state_bootstrap import bootstrap_owner_runtime_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bootstrap-owner-state", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    state = Path(args.state)
    root = Path(args.repo_root)
    state.mkdir(parents=True, exist_ok=True)
    bootstrap = None
    if args.bootstrap_owner_state:
        bootstrap = bootstrap_owner_runtime_state(state, repo_root=root)

    result = run_authority_opportunity_explorer(state, repo_root=root)
    if bootstrap is not None:
        result = {**result, "runtime_bootstrap": bootstrap}

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
