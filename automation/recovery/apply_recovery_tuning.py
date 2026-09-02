"""Apply learned recovery tuning to a temporary runtime registry.

Only operational knobs are adjusted: stale detection thresholds and per-run dispatch
budget. Authority/provider/repository/workflow boundaries are copied unchanged.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_tuning(registry: dict[str, Any], tuning: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(registry)
    policy = out.setdefault("policy", {})
    if not isinstance(policy, dict):
        raise ValueError("registry policy must be an object")

    base_cap = max(0, min(int(policy.get("max_recovery_dispatches_per_run", 3)), 10))
    enabled = tuning.get("enabled") is True and not tuning.get("active_controls")
    if not enabled:
        policy["max_recovery_dispatches_per_run"] = 0
        out["runtime_tuning"] = {
            "enabled": False,
            "reason": "active_control_or_tuning_disabled",
            "stale_after_multiplier": 1.0,
            "max_dispatches_per_run": 0,
        }
        return out

    requested_budget = int(tuning.get("max_dispatches_per_run", base_cap))
    dispatch_budget = max(0, min(requested_budget, base_cap))
    multiplier = _clamp(float(tuning.get("stale_after_multiplier", 1.0)), 0.5, 1.0)
    policy["max_recovery_dispatches_per_run"] = dispatch_budget

    workers = out.get("workers", [])
    if isinstance(workers, list):
        for worker in workers:
            if not isinstance(worker, dict):
                continue
            base_stale = max(60, min(int(worker.get("stale_after_seconds", 3600)), 7 * 24 * 3600))
            worker["stale_after_seconds"] = max(60, int(round(base_stale * multiplier)))

    out["runtime_tuning"] = {
        "enabled": True,
        "stale_after_multiplier": multiplier,
        "max_dispatches_per_run": dispatch_budget,
        "source": "production_stop_learning",
    }
    return out


def apply_dynamic_tuning(dynamic: dict[str, Any], tuning: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dynamic)
    enabled = tuning.get("enabled") is True and not tuning.get("active_controls")
    if not enabled:
        return out
    multiplier = _clamp(float(tuning.get("stale_after_multiplier", 1.0)), 0.5, 1.0)
    rows = out.get("workers", [])
    if isinstance(rows, list):
        for worker in rows:
            if not isinstance(worker, dict):
                continue
            base_stale = max(60, min(int(worker.get("stale_after_seconds", 3600)), 7 * 24 * 3600))
            worker["stale_after_seconds"] = max(60, int(round(base_stale * multiplier)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply production recovery tuning")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tuning", required=True)
    parser.add_argument("--dynamic-workers")
    parser.add_argument("--out-registry", required=True)
    parser.add_argument("--out-dynamic")
    args = parser.parse_args()

    registry = _load(args.registry)
    tuning = _load(args.tuning)
    tuned = apply_tuning(registry, tuning)
    Path(args.out_registry).write_text(json.dumps(tuned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.dynamic_workers and args.out_dynamic:
        dynamic = _load(args.dynamic_workers)
        tuned_dynamic = apply_dynamic_tuning(dynamic, tuning)
        Path(args.out_dynamic).write_text(
            json.dumps(tuned_dynamic, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(tuned.get("runtime_tuning", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
