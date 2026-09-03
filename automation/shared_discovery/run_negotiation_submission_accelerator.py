#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.negotiation_submission_accelerator import run_submission_accelerator


def main() -> int:
    parser = argparse.ArgumentParser(description="Route persistent root candidates into the existing META/X/SENJU approval flow")
    parser.add_argument("--state", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_submission_accelerator(args.state)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
