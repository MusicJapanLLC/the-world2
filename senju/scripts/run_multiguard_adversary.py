#!/usr/bin/env python3
"""Run the deterministic offline adversary campaign across Senju guard surfaces."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from senju.multiguard_adversary import TARGETS, build_campaign, run_campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        choices=("all", *TARGETS),
        help="target to probe; repeat for multiple targets (default: all)",
    )
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    parser.add_argument("--json-out", type=Path, help="also write the report to this path")
    parser.add_argument(
        "--fail-on-surprise",
        action="store_true",
        help="exit 1 when any probe disagrees with its security contract",
    )
    args = parser.parse_args()

    requested = args.target or ["all"]
    selected = TARGETS if "all" in requested else tuple(dict.fromkeys(requested))
    report = run_campaign(build_campaign(targets=selected))
    encoded = report.to_json(indent=None if args.compact else 2)
    print(encoded)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")

    if args.fail_on_surprise and not report.passed:
        print(
            f"multiguard surprise gate failed: count={report.surprising_count} "
            f"risk_score={report.risk_score} side_effect_violations={report.side_effect_violation_count}",
            file=sys.stderr,
        )
        for result in report.surprising:
            print(
                f"SURPRISE {result.case.target}/{result.case.name} "
                f"expected={result.case.should_allow} observed={result.allowed} "
                f"side_effect_calls={result.side_effect_calls} "
                f"guard_exception={result.guard_exception_type} "
                f"harness_exception={result.harness_exception_type} "
                f"detail={result.detail}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
