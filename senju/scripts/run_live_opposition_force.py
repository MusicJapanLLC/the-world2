#!/usr/bin/env python3
"""Run the live-bound Senju opposition force against real guard implementations."""
from __future__ import annotations

import argparse
from pathlib import Path

from senju.opposition_force import run_live_opposition_force


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    parser.add_argument("--json-out", type=Path, help="also write the report to this path")
    parser.add_argument(
        "--fail-on-surprise",
        action="store_true",
        help="exit 1 on a surrogate binding or adversary surprise",
    )
    args = parser.parse_args()

    report = run_live_opposition_force()
    encoded = report.to_json(indent=None if args.compact else 2)
    print(encoded)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")

    if args.fail_on_surprise and not report.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
