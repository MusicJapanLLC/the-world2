#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.authority_signal_bridge import run_authority_signal_bridge


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect discovery, similarity, and AI consensus to the authority pipeline")
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_authority_signal_bridge(args.state)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
