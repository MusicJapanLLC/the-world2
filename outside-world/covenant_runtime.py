#!/usr/bin/env python3
"""Bind THE COVENANT to real-world missions before external dispatch.

This module does not create new authority. It turns the existing Covenant into
runtime metadata so external executors can preserve doctrine, autonomy tier,
evidence expectations, privacy class, and the post-result learning loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_DUTIES = ("TRUTH", "SERVICE", "AUTONOMY", "IMPROVEMENT")
LANE_DUTY = {
    "PUBLIC_WEB": "AUTONOMY",
    "PUBLIC_YOUTUBE": "TRUTH",
    "PUBLIC_GITHUB": "IMPROVEMENT",
    "PUBLIC_RESEARCH": "TRUTH",
    "PUBLIC_BUILDERS": "SERVICE",
}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stable_duty(mission: dict[str, Any], duties: tuple[str, ...]) -> str:
    lane = str(mission.get("lane") or "")
    if lane in LANE_DUTY and LANE_DUTY[lane] in duties:
        return LANE_DUTY[lane]
    key = str(mission.get("mission_id") or mission.get("citizen_id") or lane)
    index = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % len(duties)
    return duties[index]


def bind_plan(plan: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(plan)
    cfg = policy.get("covenant_runtime") or {}
    if not cfg.get("required", True):
        return out

    duties_raw = cfg.get("duties") or list(DEFAULT_DUTIES)
    duties = tuple(str(x).upper() for x in duties_raw if str(x).strip())
    if not duties:
        raise ValueError("covenant_runtime.duties must not be empty")

    doctrine = str(cfg.get("doctrine") or policy.get("principle") or "LIMITLESS_MIND_BOUNDED_EXECUTION")
    outcome_loop = list(cfg.get("outcome_loop") or ["ACT", "VERIFY", "LOG", "LEARN", "IMPROVE"])
    evidence_contract = str(
        cfg.get("evidence_contract")
        or "Return verifiable source/result evidence. Never report success without evidence."
    )
    privacy_class = str(cfg.get("default_privacy_class") or "public")
    default_tier = str(cfg.get("default_autonomy_tier") or "T0")

    missions = list(out.get("missions") or [])
    for mission in missions:
        duty = _stable_duty(mission, duties)
        objective = str(mission.get("objective") or "").strip()
        mission["covenant"] = {
            "doctrine": doctrine,
            "duty": duty,
            "autonomy_tier": str(mission.get("autonomy_tier") or default_tier),
            "reality_contact": str(mission.get("lane") or mission.get("action") or "EXTERNAL"),
            "value_hypothesis": objective or "Produce one externally verifiable useful result.",
            "evidence_contract": evidence_contract,
            "privacy_class": str(mission.get("privacy_class") or privacy_class),
            "outcome_loop": outcome_loop,
            "failure_confession_required": True,
            "next_vow_required": True,
        }

    coverage = sum(1 for m in missions if isinstance(m.get("covenant"), dict))
    evidence_coverage = sum(
        1 for m in missions
        if isinstance(m.get("covenant"), dict) and bool(m["covenant"].get("evidence_contract"))
    )
    out["covenant_binding"] = {
        "required": True,
        "doctrine": doctrine,
        "missions_total": len(missions),
        "missions_bound": coverage,
        "coverage_ratio": 1.0 if not missions else coverage / len(missions),
        "evidence_coverage_ratio": 1.0 if not missions else evidence_coverage / len(missions),
        "outcome_loop": outcome_loop,
    }
    return out


def validate_bound_plan(plan: dict[str, Any]) -> None:
    missions = list(plan.get("missions") or [])
    binding = plan.get("covenant_binding") or {}
    if binding.get("required") and binding.get("missions_bound") != len(missions):
        raise ValueError("not every external mission is Covenant-bound")

    required = {
        "doctrine",
        "duty",
        "autonomy_tier",
        "reality_contact",
        "value_hypothesis",
        "evidence_contract",
        "privacy_class",
        "outcome_loop",
        "failure_confession_required",
        "next_vow_required",
    }
    for mission in missions:
        covenant = mission.get("covenant")
        if not isinstance(covenant, dict):
            raise ValueError(f"mission {mission.get('mission_id')} missing covenant")
        missing = []
        for key in required:
            value = covenant.get(key)
            if value is None or value == "" or value == []:
                missing.append(key)
        if missing:
            raise ValueError(f"mission {mission.get('mission_id')} missing covenant fields: {sorted(missing)}")


def render_report(plan: dict[str, Any]) -> str:
    binding = plan.get("covenant_binding") or {}
    counts: dict[str, int] = {}
    for mission in plan.get("missions") or []:
        duty = str((mission.get("covenant") or {}).get("duty") or "UNBOUND")
        counts[duty] = counts.get(duty, 0) + 1

    lines = [
        "# THE WORLD — Covenant Runtime Binding",
        "",
        f"- doctrine: `{binding.get('doctrine')}`",
        f"- missions: **{binding.get('missions_total', 0)}**",
        f"- Covenant-bound: **{binding.get('missions_bound', 0)}**",
        f"- coverage: **{binding.get('coverage_ratio', 0):.0%}**",
        f"- evidence coverage: **{binding.get('evidence_coverage_ratio', 0):.0%}**",
        f"- loop: `{' -> '.join(binding.get('outcome_loop') or [])}`",
        "",
        "## Duty distribution",
    ]
    lines.extend(f"- {duty}: {count}" for duty, count in sorted(counts.items()))
    lines += [
        "",
        "A mission is not counted as Covenant-bound unless the dispatch payload carries",
        "its duty, autonomy tier, real-world contact, value hypothesis, evidence contract,",
        "privacy class, failure-confession requirement, and next-vow requirement.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--report", default="covenant-runtime-report.md")
    args = parser.parse_args()

    if args.in_place and args.out:
        raise SystemExit("use either --in-place or --out")
    if not args.in_place and not args.out:
        raise SystemExit("--out is required unless --in-place is used")

    plan = load_json(args.plan)
    policy = load_json(args.policy)
    bound = bind_plan(plan, policy)
    validate_bound_plan(bound)

    destination = Path(args.plan if args.in_place else args.out)
    destination.write_text(json.dumps(bound, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render_report(bound), encoding="utf-8")
    print(json.dumps(bound.get("covenant_binding") or {}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
