#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.reviewed_root_authority_negotiation import run_reviewed_root_authority_negotiation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run intake-gated persistent Root Authority negotiation")
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_reviewed_root_authority_negotiation(args.state, repo_root=args.repo_root)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
