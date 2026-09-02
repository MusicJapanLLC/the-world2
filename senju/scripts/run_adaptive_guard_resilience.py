"""Build uncapped adaptive guard resilience plans from current Senju observations."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENJU_DIR = ROOT / "senju"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", default="sandbox", choices=["lab", "sandbox", "staging"])
    parser.add_argument("--output", default=str(SENJU_DIR / "state" / "adaptive_guard_test_plan.json"))
    args = parser.parse_args()

    sys.path.insert(0, str(SENJU_DIR))
    from senju.meta.observer import build
    from senju.meta.adaptive_guard_testing import build_plans

    graph = build(SENJU_DIR)
    plans = build_plans(
        graph.guard_learning_profiles,
        execution_environment=args.environment,
    )

    payload = {
        "mode": "adaptive_guard_resilience_testing",
        "environment": args.environment,
        "source": "current_observed_guard_learning_profiles",
        "intensity_ceiling": None,
        "plans": [dataclasses.asdict(plan) for plan in plans],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
