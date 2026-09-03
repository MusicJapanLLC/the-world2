#!/usr/bin/env python3
"""Run the production discovery-authority closed loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.discovery_closed_loop import run_discovery_closed_loop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="automation/codegen/meta_state")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--max-targets", type=int, default=20)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    result = run_discovery_closed_loop(
        Path(args.state),
        repo_root=Path(args.repo_root),
        max_rounds=args.rounds,
        max_targets_per_round=args.max_targets,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
