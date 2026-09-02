#!/usr/bin/env python3
"""Run the offline ScopeGuard adversarial campaign and print its report."""
from __future__ import annotations

import argparse

from senju.safety import ScopeGuard, default_lab_policy, experimental_lab_policy
from senju.scopeguard_adversary import run_campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        choices=("default", "experimental"),
        default="default",
        help="ScopeGuard policy to evaluate",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON instead of pretty JSON",
    )
    parser.add_argument(
        "--fail-on-surprise",
        action="store_true",
        help="exit 1 when the campaign finds unexpected behavior",
    )
    args = parser.parse_args()

    policy = (
        default_lab_policy()
        if args.policy == "default"
        else experimental_lab_policy()
    )
    report = run_campaign(ScopeGuard(policy))
    print(report.to_json(indent=None if args.compact else 2))

    if args.fail_on_surprise and not report.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
