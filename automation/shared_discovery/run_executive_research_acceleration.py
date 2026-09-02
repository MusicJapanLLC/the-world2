#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.executive_research_acceleration import run_executive_research_acceleration


def main() -> int:
    parser = argparse.ArgumentParser(description="Run proposal-only META/X/SENJU research acceleration")
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_executive_research_acceleration(Path(args.state))
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
