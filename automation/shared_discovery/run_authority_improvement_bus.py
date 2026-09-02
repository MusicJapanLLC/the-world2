#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.authority_improvement_bus import run_authority_improvement_bus


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuse authority/discovery evidence into shared improvement work")
    parser.add_argument("--state", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_authority_improvement_bus(Path(args.state))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
