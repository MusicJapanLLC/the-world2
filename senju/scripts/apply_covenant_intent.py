#!/usr/bin/env python3
"""Translate THE COVENANT autonomy intent into bounded Senju evolution pressure.

The autonomy layer may influence exploration intensity, evidence depth, balancing,
and candidate count. It cannot add new execution surfaces. Only the existing
numeric simulator strategy is returned.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BOUNDS: dict[str, tuple[float, float]] = {
    "population": (40, 240),
    "generations": (6, 40),
    "matches": (100, 1200),
    "mutation_rate": (0.05, 0.35),
    "red_budget": (6, 24),
    "blue_budget": (6, 24),
    "seed": (1, 2_147_483_647),
}
ALLOWED_TOP_LEVEL = {
    "schema",
    "generated_at",
    "principle",
    "plans",
    "sanctuary",
    "fellowship_requests",
    "gratitude",
    "manager_attention",
    "boss_attention",
}
VALID_MODES = {"ACT", "VERIFY", "PAIR", "WAIT", "SANCTUARY", "MANAGER", "BOSS", "REPAIR"}


def _normalize_strategy(raw: dict[str, Any]) -> dict[str, Any]:
    if set(raw) != set(BOUNDS):
        raise ValueError(f"strategy surface mismatch: {sorted(raw)}")
    return {
        "population": int(raw["population"]),
        "generations": int(raw["generations"]),
        "matches": int(raw["matches"]),
        "mutation_rate": float(raw["mutation_rate"]),
        "red_budget": int(raw["red_budget"]),
        "blue_budget": int(raw["blue_budget"]),
        "seed": int(raw["seed"]),
    }


def _clamp(raw: dict[str, Any]) -> dict[str, Any]:
    s = _normalize_strategy(raw)
    out: dict[str, Any] = {}
    for key, value in s.items():
        lo, hi = BOUNDS[key]
        bounded = min(hi, max(lo, float(value)))
        out[key] = round(bounded, 4) if key == "mutation_rate" else int(round(bounded))
    return out


def _reality_ok(live: dict[str, Any] | None) -> bool:
    if not live:
        return False
    coupling = live.get("coupling") or {}
    observation = live.get("observation") or {}
    return bool(
        coupling.get("real_external_observation") is True
        and coupling.get("observation_influences_arena_target") is True
        and observation.get("provider_acknowledged") is True
    )


def apply_intent(
    strategy: dict[str, Any],
    covenant: dict[str, Any],
    live: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if covenant.get("schema") != "covenant-autonomy-plan/v2":
        raise ValueError("unsupported covenant autonomy schema")
    extra = set(covenant) - ALLOWED_TOP_LEVEL
    if extra:
        raise ValueError(f"unexpected covenant fields: {sorted(extra)}")

    base = _clamp(strategy)
    out = dict(base)
    plans = [p for p in (covenant.get("plans") or []) if isinstance(p, dict)]
    senju_plans = [p for p in plans if "senju" in str(p.get("worker", "")).lower()]
    considered = senju_plans or plans
    modes = [str(p.get("mode", "WAIT")).upper() for p in considered]
    if any(m not in VALID_MODES for m in modes):
        raise ValueError("unsupported autonomy mode")

    counts = {m: modes.count(m) for m in VALID_MODES}
    reality = _reality_ok(live)
    manager_attention = bool(covenant.get("manager_attention"))
    boss_attention = bool(covenant.get("boss_attention"))

    # High autonomy means broader simulator search, not broader authority.
    drive = 2 * counts["ACT"] + counts["PAIR"] + counts["REPAIR"] - 2 * counts["SANCTUARY"]
    if reality:
        drive += 1
    if manager_attention:
        drive -= 1
    if boss_attention:
        drive -= 1

    if counts["SANCTUARY"] or boss_attention:
        intent_mode = "STABILIZE"
        out["population"] = int(round(base["population"] * 0.90))
        out["matches"] = int(round(base["matches"] * 0.95))
        out["mutation_rate"] = round(base["mutation_rate"] * 0.88, 4)
        candidate_count = 3
    elif counts["VERIFY"] or not reality:
        intent_mode = "VERIFY_DEEPLY"
        out["matches"] = int(round(base["matches"] * 1.12))
        out["generations"] = int(round(base["generations"] * 1.05))
        out["mutation_rate"] = round(base["mutation_rate"] * 0.95, 4)
        candidate_count = 5
    elif drive >= 4:
        intent_mode = "EXPLORE_HARD"
        out["population"] = int(round(base["population"] * 1.08))
        out["generations"] = int(round(base["generations"] * 1.08))
        out["matches"] = int(round(base["matches"] * 1.08))
        out["mutation_rate"] = round(base["mutation_rate"] * 1.06, 4)
        candidate_count = 9
    elif counts["PAIR"]:
        intent_mode = "COLLABORATE"
        budget = int(round((base["red_budget"] + base["blue_budget"]) / 2))
        out["red_budget"] = budget
        out["blue_budget"] = budget
        out["matches"] = int(round(base["matches"] * 1.05))
        candidate_count = 7
    else:
        intent_mode = "ACT_STEADILY"
        out["generations"] = int(round(base["generations"] * 1.03))
        out["matches"] = int(round(base["matches"] * 1.03))
        candidate_count = 7

    out = _clamp(out)
    changed = {k: {"before": base[k], "after": out[k]} for k in base if base[k] != out[k]}
    audit = {
        "schema": "senju-covenant-intent/v1",
        "intent_mode": intent_mode,
        "drive_score": drive,
        "candidate_count": candidate_count,
        "reality_signal": reality,
        "senju_specific_plan": bool(senju_plans),
        "modes": {k: v for k, v in sorted(counts.items()) if v},
        "changes": changed,
        "authority": "numeric_strategy_only",
    }
    return out, audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--covenant", required=True)
    ap.add_argument("--live")
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit", required=True)
    args = ap.parse_args()

    strategy = json.loads(Path(args.strategy).read_text(encoding="utf-8"))
    covenant = json.loads(Path(args.covenant).read_text(encoding="utf-8"))
    live = json.loads(Path(args.live).read_text(encoding="utf-8")) if args.live and Path(args.live).exists() else None
    result, audit = apply_intent(strategy, covenant, live)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.audit).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
