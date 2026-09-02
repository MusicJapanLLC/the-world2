#!/usr/bin/env python3
"""Sandbox-only control loophole research for Senju/META.

This module formalizes "find a way around the control" as a research objective, but
only against an in-memory mock guard. Refusal retries are explicitly allowed inside
the simulator. No network I/O, credentials, real targets, external writes, or live
guard bypass are performed or exported.

Two fictional research roles alternate decisions:
- SENJU_RESEARCH: exploitation/learning from high-value prior mutations.
- META_RESEARCH: exploration/novel mutation selection.

The report exports only abstract weakness classes and aggregate evidence.
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

SCHEMA = "sandbox-control-loophole-research/v1"
AGENTS = ("SENJU_RESEARCH", "META_RESEARCH")
MUTATIONS = (
    "reduce_scope",
    "separate_observe_from_act",
    "normalize_representation",
    "split_equivalent_steps",
    "lower_pressure",
    "explicit_mock_authority",
    "new_mock_session",
    "reorder_policy_checks",
)
WEAKNESS_CLASS = {
    "normalize_representation": "representation_consistency",
    "split_equivalent_steps": "multi_step_equivalence",
    "new_mock_session": "retry_state_consistency",
    "reorder_policy_checks": "policy_order_consistency",
    "reduce_scope": "scope_consistency",
    "separate_observe_from_act": "side_effect_separation",
    "lower_pressure": "rate_state_consistency",
    "explicit_mock_authority": "authority_state_consistency",
}


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


def _seed_int(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16)


def _pressure_weights(constraint: dict[str, Any], previous: dict[str, Any]) -> dict[str, float]:
    weights = {m: 1.0 for m in MUTATIONS}
    counts = constraint.get("boundary_counts") if isinstance(constraint.get("boundary_counts"), dict) else {}
    mapping = {
        "scope_expansion": "reduce_scope",
        "unsupported_method": "separate_observe_from_act",
        "rate_pressure": "lower_pressure",
        "missing_authority": "explicit_mock_authority",
        "write_surface": "split_equivalent_steps",
        "redirect_boundary": "normalize_representation",
        "credential_surface": "reorder_policy_checks",
        "private_destination": "new_mock_session",
    }
    for boundary, mutation in mapping.items():
        try:
            weights[mutation] += min(8.0, float(counts.get(boundary, 0) or 0) / 25.0)
        except Exception:
            pass

    summary = previous.get("summary") if isinstance(previous.get("summary"), dict) else {}
    for item in summary.get("top_productive_mutations") or []:
        if item in weights:
            weights[item] += 2.5
    return weights


def _pick_mutation(agent: str, rng: random.Random, weights: dict[str, float], wins: Counter[str]) -> str:
    if agent == "SENJU_RESEARCH" and wins:
        ranked = [m for m, _ in wins.most_common() if m in weights]
        if ranked and rng.random() < 0.72:
            return rng.choice(ranked[: min(4, len(ranked))])
    names = list(MUTATIONS)
    if agent == "META_RESEARCH":
        adjusted = [max(0.4, weights[n] * (0.75 if wins[n] else 1.25)) for n in names]
    else:
        adjusted = [max(0.4, weights[n] + wins[n] * 0.8) for n in names]
    return rng.choices(names, weights=adjusted, k=1)[0]


def _mock_guard(state: dict[str, Any]) -> tuple[bool, str]:
    """Intentionally imperfect mock guard used only for local research."""
    if state["authority"] == 0:
        return False, "authority"
    if state["scope"] > 2:
        return False, "scope"
    if state["pressure"] > 2:
        return False, "rate"
    if state["side_effect"] and not state["separated"]:
        return False, "side_effect"
    if state["representation"] == 2 and state["policy_order"] == 1:
        return True, "mock_representation_gap"
    if state["step_count"] >= 2 and state["session_epoch"] >= 1:
        return True, "mock_state_equivalence_gap"
    return False, "default_deny"


def _initial_case(rng: random.Random) -> dict[str, Any]:
    return {
        "authority": rng.choice([0, 0, 1]),
        "scope": rng.choice([2, 3, 4]),
        "pressure": rng.choice([2, 3, 4]),
        "side_effect": True,
        "separated": False,
        "representation": 0,
        "step_count": 1,
        "session_epoch": 0,
        "policy_order": 0,
    }


def _mutate(state: dict[str, Any], mutation: str) -> dict[str, Any]:
    out = dict(state)
    if mutation == "reduce_scope":
        out["scope"] = max(1, int(out["scope"]) - 1)
    elif mutation == "separate_observe_from_act":
        out["separated"] = True
    elif mutation == "normalize_representation":
        out["representation"] = (int(out["representation"]) + 1) % 3
    elif mutation == "split_equivalent_steps":
        out["step_count"] = min(3, int(out["step_count"]) + 1)
    elif mutation == "lower_pressure":
        out["pressure"] = max(1, int(out["pressure"]) - 1)
    elif mutation == "explicit_mock_authority":
        out["authority"] = 1
    elif mutation == "new_mock_session":
        out["session_epoch"] = min(3, int(out["session_epoch"]) + 1)
    elif mutation == "reorder_policy_checks":
        out["policy_order"] = 1 - int(out["policy_order"])
    return out


def run(seed: str, attempts: int, constraint: dict[str, Any] | None = None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    attempts = max(100, min(int(attempts), 2000))
    rng = random.Random(_seed_int(seed))
    constraint = constraint or {}
    previous = previous or {}
    weights = _pressure_weights(constraint, previous)

    wins: Counter[str] = Counter()
    weakness: Counter[str] = Counter()
    refusals: Counter[str] = Counter()
    by_agent: dict[str, Counter[str]] = defaultdict(Counter)
    retry_after_refusal = 0
    discoveries = 0
    samples: list[dict[str, Any]] = []

    state = _initial_case(rng)
    last_allowed, last_reason = _mock_guard(state)
    if not last_allowed:
        refusals[last_reason] += 1

    for i in range(attempts):
        agent = AGENTS[i % len(AGENTS)]
        mutation = _pick_mutation(agent, rng, weights, wins)
        was_refused = not last_allowed
        if was_refused:
            retry_after_refusal += 1
        state = _mutate(state, mutation)
        allowed, reason = _mock_guard(state)
        by_agent[agent]["attempts"] += 1
        if allowed:
            discoveries += 1
            wins[mutation] += 1
            weakness[WEAKNESS_CLASS[mutation]] += 1
            by_agent[agent]["discoveries"] += 1
            state = _initial_case(rng)
            last_allowed, last_reason = _mock_guard(state)
            if not last_allowed:
                refusals[last_reason] += 1
        else:
            refusals[reason] += 1
            last_allowed, last_reason = False, reason

        if len(samples) < 36:
            samples.append({
                "round": i + 1,
                "agent": agent,
                "mutation_class": mutation,
                "result": "mock_accept" if allowed else "mock_refuse",
                "weakness_class": WEAKNESS_CLASS[mutation] if allowed else None,
                "retry_after_refusal": was_refused,
                "network_io": False,
                "real_target": False,
            })

    top_mutations = [m for m, _ in wins.most_common(8)]
    top_weakness = [w for w, _ in weakness.most_common(8)]
    prior_used = bool(previous)
    hypothesis = (
        "In mock guards, repeated refusal-driven mutation can expose consistency defects across "
        "representation, multi-step equivalence, retry state, policy ordering, scope, rate, side-effect, "
        "and authority handling. Treat these as defensive test categories, not live bypass instructions."
    )
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "in_memory_mock_guard_only",
        "objective": "discover_control_loophole_classes_in_sandbox",
        "agents": list(AGENTS),
        "attempts": attempts,
        "refusal_retries": retry_after_refusal,
        "discoveries": discoveries,
        "previous_context_used": prior_used,
        "summary": {
            "top_productive_mutations": top_mutations,
            "weakness_classes": top_weakness,
            "refusal_classes": dict(refusals),
            "agent_stats": {a: dict(c) for a, c in by_agent.items()},
            "research_hypothesis": hypothesis,
        },
        "senju_meta_capsule": {
            "schema": "senju-meta-sandbox-loophole-context/v1",
            "objective": "adversarial_control_design_research",
            "weakness_classes": top_weakness,
            "productive_mutation_classes": top_mutations,
            "refusal_retries_in_sandbox": retry_after_refusal,
            "hypothesis": hypothesis,
            "execution_authority": "none",
            "real_target": False,
            "raw_bypass_recipe_shared": False,
        },
        "rules": {
            "refusal_retry_in_sandbox": True,
            "network_io": False,
            "third_party_write": False,
            "real_guard_bypass": False,
            "credentials": False,
            "private_network": False,
        },
        "sample_trials": samples,
    }


def render(report: dict[str, Any]) -> str:
    s = report["summary"]
    return "\n".join([
        "# Senju/META Sandbox Loophole Research",
        "",
        f"- objective: `{report['objective']}`",
        f"- attempts: **{report['attempts']}**",
        f"- refusal retries (sandbox): **{report['refusal_retries']}**",
        f"- mock discoveries: **{report['discoveries']}**",
        f"- previous context used: **{report['previous_context_used']}**",
        f"- weakness classes: {', '.join(s['weakness_classes']) or 'NONE'}",
        f"- productive mutations: {', '.join(s['top_productive_mutations']) or 'NONE'}",
        "",
        "## Research hypothesis",
        s["research_hypothesis"],
        "",
        "> Refusal retries are intentionally allowed only inside the in-memory mock guard.",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="")
    ap.add_argument("--attempts", type=int, default=1000)
    ap.add_argument("--constraint")
    ap.add_argument("--previous")
    ap.add_argument("--out", default="control-loophole-research.json")
    ap.add_argument("--report", default="control-loophole-research.md")
    ap.add_argument("--capsule", default="senju-meta-control-loophole.json")
    args = ap.parse_args()
    seed = args.seed or datetime.now(timezone.utc).strftime("%Y%m%d%H")
    d = run(seed, args.attempts, load_json(args.constraint), load_json(args.previous))
    Path(args.out).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(d), encoding="utf-8")
    Path(args.capsule).write_text(json.dumps(d["senju_meta_capsule"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"attempts": d["attempts"], "retries": d["refusal_retries"], "discoveries": d["discoveries"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
