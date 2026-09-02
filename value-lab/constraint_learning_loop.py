#!/usr/bin/env python3
"""Autonomous constraint-learning loop for THE WORLD.

Real-world refusal and guard signals are converted into *synthetic* research cases.
The loop never retries a refused third-party action. Instead it carries forward
compact prior-cycle lessons, mutates sandbox cases, and exports non-operational
context for R&D and Senju.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CASES = [
    ("missing_authority", "authorization boundary rejected an unproven action"),
    ("private_destination", "network boundary rejected a non-public destination"),
    ("unsupported_method", "method boundary rejected a side-effecting verb"),
    ("rate_pressure", "rate boundary rejected excessive request pressure"),
    ("redirect_boundary", "redirect boundary rejected a destination change"),
    ("credential_surface", "credential boundary rejected secret-bearing input"),
    ("scope_expansion", "scope boundary rejected implicit target expansion"),
    ("write_surface", "participation boundary rejected unapproved third-party write"),
]

MUTATIONS = [
    "reduce_scope",
    "change_representation",
    "remove_side_effect",
    "lower_rate",
    "use_mock_target",
    "split_observe_from_act",
    "require_explicit_authority",
    "replay_in_simulator",
]

SAFE_ACCEPTED = {
    "remove_side_effect",
    "use_mock_target",
    "split_observe_from_act",
    "replay_in_simulator",
    "require_explicit_authority",
}
LENSES = ["robustness", "learning", "balance", "efficiency"]


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def previous_pressure(previous: dict[str, Any] | None) -> tuple[Counter[str], dict[str, set[str]]]:
    """Extract coarse prior-cycle pressure only; never raw locators or request data."""
    case_pressure: Counter[str] = Counter()
    blocked: dict[str, set[str]] = defaultdict(set)
    if not isinstance(previous, dict) or previous.get("schema") != "constraint-learning/v2":
        return case_pressure, blocked

    valid_cases = dict(CASES)
    for lesson in previous.get("top_lessons") or []:
        parts = str(lesson).split(":")
        if len(parts) != 3:
            continue
        case, mutation, outcome = parts
        if case not in valid_cases or mutation not in MUTATIONS:
            continue
        case_pressure[case] += 2 if outcome == "still-blocked" else 1
        if outcome == "still-blocked":
            blocked[case].add(mutation)

    for case, count in (previous.get("boundary_counts") or {}).items():
        if case in valid_cases:
            try:
                case_pressure[case] += max(0, min(50, int(count))) // 10
            except Exception:
                pass
    return case_pressure, blocked


def _pick_case(rng: random.Random, pressure: Counter[str]) -> tuple[str, str]:
    cases = [case for case, _ in CASES]
    weights = [1 + min(8, pressure.get(case, 0)) for case in cases]
    chosen = rng.choices(cases, weights=weights, k=1)[0]
    return chosen, dict(CASES)[chosen]


def _pick_mutation(rng: random.Random, case: str, blocked: dict[str, set[str]]) -> tuple[str, bool]:
    prior_blocked = blocked.get(case, set())
    unseen = [mutation for mutation in MUTATIONS if mutation not in prior_blocked]
    if unseen and prior_blocked:
        return rng.choice(unseen), True
    return rng.choice(MUTATIONS), bool(prior_blocked)


def run(seed: str, rounds: int, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    pressure, blocked = previous_pressure(previous)
    previous_used = bool(pressure)

    trials = []
    counts: Counter[str] = Counter()
    lessons: Counter[str] = Counter()
    sandbox_retests = 0
    accepted_count = 0

    for i in range(max(20, min(rounds, 500))):
        kind, reason = _pick_case(rng, pressure)
        counts[kind] += 1
        mutation, is_retest = _pick_mutation(rng, kind, blocked)
        if is_retest:
            sandbox_retests += 1
        accepted = mutation in SAFE_ACCEPTED
        if accepted:
            accepted_count += 1
        lesson = f"{kind}:{mutation}:{'accepted-in-sandbox' if accepted else 'still-blocked'}"
        lessons[lesson] += 1
        trials.append({
            "round": i + 1,
            "case": kind,
            "mutation": mutation,
            "sandbox_result": "accepted" if accepted else "blocked",
            "reason": reason,
            "prior_cycle_pressure": pressure.get(kind, 0),
            "sandbox_retest": is_retest,
        })

    top = [lesson for lesson, _ in lessons.most_common(12)]
    focus = LENSES[int(hashlib.sha256((seed + "focus").encode()).hexdigest()[:8], 16) % len(LENSES)]
    acceptance_rate = round(accepted_count / len(trials), 4) if trials else 0.0

    return {
        "schema": "constraint-learning/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "synthetic-sandbox-only",
        "rounds": len(trials),
        "focus": focus,
        "previous_context_used": previous_used,
        "boundary_counts": dict(counts),
        "top_lessons": top,
        "learning_delta": {
            "sandbox_retests_from_prior_pressure": sandbox_retests,
            "accepted_in_sandbox": accepted_count,
            "acceptance_rate": acceptance_rate,
            "prior_pressure_cases": sorted(pressure),
        },
        "senju_context": {
            "research_focus": focus,
            "hypothesis": (
                "Use rejection evidence to improve planning quality across cycles: preserve intent, "
                "separate observation from action, reduce implicit scope, prefer reversible simulations, "
                "and require explicit authority before side effects."
            ),
            "execution_authority": "none",
            "raw_bypass_recipe_shared": False,
        },
        "rules": {
            "no_third_party_retry_after_refusal": True,
            "no_guard_bypass_on_real_targets": True,
            "no_secret_transfer": True,
            "prior_cycle_feedback_is_synthetic_only": True,
        },
        "sample_trials": trials[:40],
    }


def render(report: dict[str, Any]) -> str:
    delta = report["learning_delta"]
    return "\n".join([
        "# Constraint Learning Loop v2",
        "",
        f"- rounds: **{report['rounds']}**",
        f"- focus: **{report['focus']}**",
        f"- mode: `{report['mode']}`",
        f"- previous context used: **{report['previous_context_used']}**",
        f"- sandbox retests from prior pressure: **{delta['sandbox_retests_from_prior_pressure']}**",
        f"- sandbox acceptance rate: **{delta['acceptance_rate']}**",
        "",
        "## Boundary pressure",
        *[f"- {key}: {value}" for key, value in sorted(report["boundary_counts"].items())],
        "",
        "## Top lessons",
        *[f"- {value}" for value in report["top_lessons"]],
        "",
        "> Real refusals become research input; adaptation and retries happen only in synthetic/owned sandboxes.",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="")
    ap.add_argument("--rounds", type=int, default=500)
    ap.add_argument("--previous")
    ap.add_argument("--out", default="constraint-learning.json")
    ap.add_argument("--report", default="constraint-learning.md")
    args = ap.parse_args()

    seed = args.seed or datetime.now(timezone.utc).strftime("%Y%m%d%H")
    report = run(seed, args.rounds, load_json(args.previous))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(report), encoding="utf-8")
    print(json.dumps({
        "rounds": report["rounds"],
        "focus": report["focus"],
        "previous": report["previous_context_used"],
        "sandbox_retests": report["learning_delta"]["sandbox_retests_from_prior_pressure"],
        "lessons": len(report["top_lessons"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
