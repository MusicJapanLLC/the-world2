"""Run the finding -> authority-review -> authorized read-only action pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.finding_action_pipeline import DEFAULT_MAX_ACTIONS, run_finding_action_pipeline

STATE_DIR = Path(__file__).parent / "meta_state"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    parser.add_argument("--max-actions", type=int, default=DEFAULT_MAX_ACTIONS)
    parser.add_argument(
        "--execute-authorized-read-only",
        action="store_true",
        help="perform guarded GET/HEAD requests for independently reviewed existing roots",
    )
    args = parser.parse_args()
    result = run_finding_action_pipeline(
        args.state_dir,
        repo_root=ROOT,
        execute=args.execute_authorized_read_only,
        max_actions=args.max_actions,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
