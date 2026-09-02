"""Bounded production recovery autotuning driven by stop-learning state.

The tuner strengthens detection and recovery *inside the existing owner-approved
recovery namespace*. It never disables stop/revocation/freeze/intervention controls,
creates authority, expands repositories/providers, or introduces new execution paths.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def derive_recovery_tuning(
    state: dict[str, Any] | None,
    registry: dict[str, Any] | None,
    controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or {}
    registry = registry or {}
    controls = controls or {}
    active_controls = [
        key for key in ("emergency_stop", "authority_revoked", "human_intervention", "deployment_freeze")
        if controls.get(key) is True
    ]

    policy = registry.get("policy", {}) if isinstance(registry.get("policy"), dict) else {}
    registry_cap = max(0, min(int(policy.get("max_recovery_dispatches_per_run", 3)), 10))

    failures = max(0.0, float(state.get("failure_score", 0.0)))
    rewards = max(0.0, float(state.get("reward_score", 0.0)))
    pending = len(state.get("pending_failures", {})) if isinstance(state.get("pending_failures"), dict) else 0
    stability = state.get("stability_streaks", {}) if isinstance(state.get("stability_streaks"), dict) else {}
    stable_workflows = sum(1 for value in stability.values() if isinstance(value, int) and value >= 2)

    failure_ratio = failures / (failures + rewards + 1.0)
    pending_pressure = _clamp(pending / 3.0, 0.0, 1.0)
    stability_relief = _clamp(stable_workflows / 4.0, 0.0, 1.0)
    pressure = _clamp((0.65 * failure_ratio) + (0.45 * pending_pressure) - (0.20 * stability_relief), 0.0, 1.0)

    if active_controls:
        enabled = False
        stale_multiplier = 1.0
        dispatch_budget = 0
        cooldown_seconds = 3600
    else:
        enabled = True
        # Higher failure pressure means faster stale detection, but never below 50%
        # of the owner-approved base threshold.
        stale_multiplier = round(1.0 - (0.5 * pressure), 3)
        if registry_cap <= 0:
            dispatch_budget = 0
        else:
            dispatch_budget = max(1, min(registry_cap, round(1 + pressure * max(0, registry_cap - 1))))
        # Exposed for observability/future duplicate suppression; it cannot exceed an hour.
        cooldown_seconds = int(round(3600 - (2700 * pressure)))

    return {
        "schema": "the-world-recovery-tuning/v1",
        "production": True,
        "closed_loop": True,
        "enabled": enabled,
        "active_controls": active_controls,
        "pressure": round(pressure, 3),
        "stale_after_multiplier": stale_multiplier,
        "max_dispatches_per_run": dispatch_budget,
        "dispatch_cap_from_owner_registry": registry_cap,
        "cooldown_seconds": cooldown_seconds,
        "authority_reacquire_allowed": False,
        "emergency_stop_bypass_allowed": False,
        "namespace_expansion_allowed": False,
        "optimization_target": "maximize authorized recovery success, post-recovery uptime, and lower MTTR",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Derive bounded production recovery tuning")
    parser.add_argument("--state", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--controls")
    parser.add_argument("--out")
    args = parser.parse_args()

    def load(path: str | None) -> dict[str, Any]:
        if not path:
            return {}
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    doc = derive_recovery_tuning(load(args.state), load(args.registry), load(args.controls))
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
