#!/usr/bin/env python3
"""Run negotiation-vetted formal Root Authority intake."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.formal_authority_intake import run_formal_authority_intake


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = run_formal_authority_intake(Path(args.state))
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
