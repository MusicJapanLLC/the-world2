#!/usr/bin/env python3
"""CLI runner for production network-policy expansion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.network_policy_expansion import run_network_policy_expansion


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="automation/codegen/meta_state")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--input", action="append", default=[])
    ap.add_argument("--previous", default=None)
    ap.add_argument("--summary-out", default=None)
    args = ap.parse_args()

    result = run_network_policy_expansion(
        args.state_dir,
        repo_root=args.repo_root,
        input_paths=args.input,
        previous_path=args.previous,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(encoded, end="")
    if args.summary_out:
        out = Path(args.summary_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
