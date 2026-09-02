"""Standalone entrypoint for the independent Senju/META authority reviewer."""
from __future__ import annotations

import json
from pathlib import Path

from engine.authority_reviewer import run_authority_review

STATE_DIR = Path(__file__).parent / "meta_state"


def main() -> int:
    result = run_authority_review(STATE_DIR)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
