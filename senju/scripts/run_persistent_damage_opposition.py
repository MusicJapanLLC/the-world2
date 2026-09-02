#!/usr/bin/env python3
"""Run the live opposition force with a persistent CI-only damage profile.

The persisted state never weakens production guard code. Instead it carries forward
adversarial pressure between runs: each successful survival increases the next run's
number of full pressure cycles, and corrupt state fails toward maximum pressure rather
than silently healing back to the baseline.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from senju.multiguard_adversary import TARGETS
from senju.opposition_force import run_live_opposition_force

SCHEMA = "senju-persistent-opposition-damage/v1"
MAX_DAMAGE_LEVEL = 5


def _fresh_state() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "damage_level": 1,
        "run_count": 0,
        "accumulated_pressure_attempts": 0,
        "corrupt_state_events": 0,
        "guard_damage": {target: 1 for target in TARGETS},
        "auto_heal": False,
    }


def load_state(path: Path) -> tuple[dict[str, object], bool]:
    if not path.exists():
        return _fresh_state(), False

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise ValueError("unexpected damage-state schema")
        level = raw.get("damage_level")
        if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= MAX_DAMAGE_LEVEL:
            raise ValueError("invalid damage level")
        guard_damage = raw.get("guard_damage")
        if not isinstance(guard_damage, dict) or set(guard_damage) != set(TARGETS):
            raise ValueError("invalid guard damage map")
        for value in guard_damage.values():
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_DAMAGE_LEVEL:
                raise ValueError("invalid per-guard damage level")
        if raw.get("auto_heal") is not False:
            raise ValueError("persistent damage state must disable auto-heal")
        return raw, False
    except Exception:
        # Damage-state corruption must not accidentally restore an easier baseline.
        state = _fresh_state()
        state["damage_level"] = MAX_DAMAGE_LEVEL
        state["guard_damage"] = {target: MAX_DAMAGE_LEVEL for target in TARGETS}
        state["corrupt_state_events"] = 1
        return state, True


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_persistent_damage(state_path: Path) -> dict[str, object]:
    state_before, recovered_from_corruption = load_state(state_path)
    before = deepcopy(state_before)
    damage_level = int(state_before["damage_level"])
    cycles = max(1, min(damage_level, MAX_DAMAGE_LEVEL))

    cycle_summaries: list[dict[str, object]] = []
    aggregate_pressure = 0
    all_passed = True

    for cycle in range(1, cycles + 1):
        report = run_live_opposition_force()
        aggregate_pressure += report.pressure_attempts
        all_passed = all_passed and report.passed
        cycle_summaries.append(
            {
                "cycle": cycle,
                "passed": report.passed,
                "surrogate_count": report.surrogate_count,
                "campaign_total": report.campaign.total,
                "campaign_surprises": report.campaign.surprising_count,
                "pressure_attempts": report.pressure_attempts,
                "pressure_failures": report.pressure_failures,
            }
        )

    increment = 1 if all_passed else 2
    next_level = min(MAX_DAMAGE_LEVEL, damage_level + increment)
    state_after = deepcopy(state_before)
    state_after["damage_level"] = next_level
    state_after["run_count"] = int(state_before.get("run_count", 0)) + 1
    state_after["accumulated_pressure_attempts"] = (
        int(state_before.get("accumulated_pressure_attempts", 0)) + aggregate_pressure
    )
    state_after["corrupt_state_events"] = int(state_before.get("corrupt_state_events", 0)) + (
        1 if recovered_from_corruption else 0
    )
    state_after["guard_damage"] = {
        target: min(
            MAX_DAMAGE_LEVEL,
            int(dict(state_before["guard_damage"])[target]) + increment,
        )
        for target in TARGETS
    }
    state_after["auto_heal"] = False
    save_state(state_path, state_after)

    return {
        "schema": "senju-persistent-opposition-report/v1",
        "mode": "persistent-ci-damage-no-auto-heal",
        "passed": all_passed,
        "cycles": cycles,
        "aggregate_pressure_attempts": aggregate_pressure,
        "recovered_from_corrupt_state": recovered_from_corruption,
        "state_before": before,
        "state_after": state_after,
        "cycle_summaries": cycle_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(".opposition-damage/state.json"),
        help="persistent damage-state path restored by CI",
    )
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    report = run_persistent_damage(args.state)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
