#!/usr/bin/env python3
"""Provision bounded direct worker fleets for META and X."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENJU_DIR = ROOT / "senju"
STATE_DIR = SENJU_DIR / "state"


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision bounded META/X child fleets")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    args = parser.parse_args()

    sys.path.insert(0, str(SENJU_DIR))
    from senju.meta.agent_fleet import provision_meta_x_fleets

    result = provision_meta_x_fleets(args.state_dir, count=args.count)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
