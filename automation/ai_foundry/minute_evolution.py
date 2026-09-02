#!/usr/bin/env python3
"""Bounded minute-scale strategy evolution for THE WORLD AI development.

This does NOT retrain or mutate model weights. It evolves the engineering strategy
used by the Agent Factory. The minute loop is deliberately state-only; code-level
changes remain behind the existing Agent Factory policy, tests and PR gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FOCUS_ORDER = (
    "correctness",
    "architecture",
    "reliability",
    "security",
    "observability",
    "efficiency",
    "productization",
)

PARAM_BOUNDS = {
    "verification_depth": (1, 5),
    "test_budget": (1, 5),
    "adversarial_review": (0, 4),
    "observability_depth": (1, 5),
    "memory_reuse": (1, 5),
    "artifact_priority": (1, 5),
    "parallel_research": (1, 5),
    "change_scope": (1, 5),
    "exploration_rate": (0.05, 0.35),
}

DEFAULT_PARAMS = {
    "verification_depth": 3,
    "test_budget": 3,
    "adversarial_review": 2,
    "observability_depth": 3,
    "memory_reuse": 3,
    "artifact_priority": 4,
    "parallel_research": 3,
    "change_scope": 2,
    "exploration_rate": 0.16,
}


def _cap(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 3)


def quality_vector(params: dict[str, Any]) -> dict[str, float]:
    v = float(params["verification_depth"])
    t = float(params["test_budget"])
    a = float(params["adversarial_review"])
    o = float(params["observability_depth"])
    m = float(params["memory_reuse"])
    p = float(params["artifact_priority"])
    r = float(params["parallel_research"])
    s = float(params["change_scope"])
    e = float(params["exploration_rate"])
    return {
        "correctness": _cap(49 + 7.0 * v + 5.0 * t + 2.0 * m - 2.5 * s),
        "architecture": _cap(48 + 4.5 * v + 4.0 * m + 3.0 * p - 2.0 * s),
        "reliability": _cap(47 + 4.5 * v + 4.0 * t + 5.5 * o - 18.0 * e),
        "security": _cap(45 + 9.0 * a + 4.0 * v - 3.0 * s),
        "observability": _cap(43 + 10.0 * o + 2.0 * m),
        "efficiency": _cap(58 + 5.0 * r - 2.3 * t - 2.0 * v - 1.8 * a - 7.0 * e),
        "productization": _cap(43 + 9.0 * p + 3.0 * m + 2.0 * o),
    }


def _proxy_score(vector: dict[str, float]) -> float:
    # Safety/correctness are intentionally weighted above raw throughput.
    weights = {
        "correctness": 1.4,
        "architecture": 1.0,
        "reliability": 1.3,
        "security": 1.3,
        "observability": 0.9,
        "efficiency": 0.8,
        "productization": 1.0,
    }
    total = sum(vector[k] * w for k, w in weights.items())
    return round(total / sum(weights.values()), 3)


def initial_state() -> dict[str, Any]:
    vector = quality_vector(DEFAULT_PARAMS)
    return {
        "schema": "the-world-ai-foundry-state/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generation": 0,
        "curriculum_level": 1,
        "champion": {
            "id": "AI-DEV-CHAMPION-G000000",
            "params": deepcopy(DEFAULT_PARAMS),
            "quality_proxy": vector,
            "proxy_score": _proxy_score(vector),
        },
        "promotions": 0,
        "rejections": 0,
        "noops": 0,
        "recent": [],
        "note": "Proxy scores steer engineering strategy only; they are not model-quality, customer-value or revenue evidence.",
    }


def _mutate_value(name: str, value: Any, rng: random.Random) -> Any:
    lo, hi = PARAM_BOUNDS[name]
    if isinstance(value, int):
        step = rng.choice((-1, 1))
        return max(int(lo), min(int(hi), value + step))
    step = rng.choice((-0.02, 0.02, -0.03, 0.03))
    return round(max(float(lo), min(float(hi), float(value) + step)), 3)


def _candidate_params(base: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    out = deepcopy(base)
    keys = list(PARAM_BOUNDS)
    for name in rng.sample(keys, k=rng.choice((1, 1, 2))):
        out[name] = _mutate_value(name, out[name], rng)
    return out


def _eligible(current: dict[str, float], candidate: dict[str, float], focus: str) -> tuple[bool, str]:
    # Never buy a focus gain by materially weakening core safety/correctness dimensions.
    for k in ("correctness", "reliability", "security"):
        if candidate[k] < current[k] - 1.0:
            return False, f"core_regression:{k}"
    if candidate[focus] < current[focus] + 0.5:
        return False, "insufficient_focus_delta"
    if _proxy_score(candidate) < _proxy_score(current) - 0.25:
        return False, "weighted_proxy_regression"
    return True, "eligible"


def evolve_once(state: dict[str, Any], seed: str) -> dict[str, Any]:
    state = deepcopy(state)
    generation = int(state.get("generation") or 0) + 1
    focus = FOCUS_ORDER[(generation - 1) % len(FOCUS_ORDER)]
    champion = state["champion"]
    current_params = champion["params"]
    current_vector = champion["quality_proxy"]

    rng = random.Random(f"{seed}:{generation}:{champion['id']}")
    candidates = []
    for idx in range(8):
        params = _candidate_params(current_params, rng)
        vector = quality_vector(params)
        ok, reason = _eligible(current_vector, vector, focus)
        candidates.append({
            "candidate": idx,
            "params": params,
            "quality_proxy": vector,
            "proxy_score": _proxy_score(vector),
            "eligible": ok,
            "reason": reason,
            "focus_delta": round(vector[focus] - current_vector[focus], 3),
        })

    eligible = [c for c in candidates if c["eligible"]]
    if eligible:
        winner = sorted(
            eligible,
            key=lambda c: (c["focus_delta"], c["proxy_score"], json.dumps(c["params"], sort_keys=True)),
            reverse=True,
        )[0]
        new_id = f"AI-DEV-CHAMPION-G{generation:06d}"
        state["champion"] = {
            "id": new_id,
            "params": winner["params"],
            "quality_proxy": winner["quality_proxy"],
            "proxy_score": winner["proxy_score"],
        }
        state["promotions"] = int(state.get("promotions") or 0) + 1
        event = {
            "generation": generation,
            "focus": focus,
            "result": "PROMOTED",
            "champion": new_id,
            "focus_delta": winner["focus_delta"],
            "proxy_score": winner["proxy_score"],
        }
    else:
        state["rejections"] = int(state.get("rejections") or 0) + len(candidates)
        state["noops"] = int(state.get("noops") or 0) + 1
        event = {
            "generation": generation,
            "focus": focus,
            "result": "NO_PROMOTION",
            "champion": champion["id"],
            "reason": "no candidate cleared regression and focus gates",
        }

    state["generation"] = generation
    state["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["recent"] = (list(state.get("recent") or []) + [event])[-30:]
    state["curriculum_level"] = min(7, 1 + int(state.get("promotions") or 0) // 12)
    return state


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    bv = before["champion"]["quality_proxy"]
    av = after["champion"]["quality_proxy"]
    return {k: round(av[k] - bv[k], 3) for k in FOCUS_ORDER}


def build_hourly_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta = _delta(before, after)
    weakest = min(after["champion"]["quality_proxy"], key=after["champion"]["quality_proxy"].get)
    material = any(abs(v) >= 0.5 for v in delta.values()) or after["champion"]["id"] != before["champion"]["id"]
    stable_payload = {
        "champion": after["champion"],
        "delta": delta,
        "weakest": weakest,
        "curriculum_level": after["curriculum_level"],
    }
    fingerprint = hashlib.sha256(json.dumps(stable_payload, sort_keys=True).encode()).hexdigest()[:20]
    return {
        "schema": "the-world-ai-foundry-hourly/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start_generation": before["generation"],
        "end_generation": after["generation"],
        "rounds": int(after["generation"]) - int(before["generation"]),
        "start_champion": before["champion"]["id"],
        "end_champion": after["champion"]["id"],
        "promotions_delta": int(after.get("promotions") or 0) - int(before.get("promotions") or 0),
        "noops_delta": int(after.get("noops") or 0) - int(before.get("noops") or 0),
        "quality_proxy_delta": delta,
        "weakest_next_focus": weakest,
        "curriculum_level": after["curriculum_level"],
        "material_delta": material,
        "report_fingerprint": fingerprint,
        "champion_params": after["champion"]["params"],
        "limitations": [
            "Minute evolution changes engineering strategy state, not model weights.",
            "Quality values are local strategy proxies; real capability requires Agent Factory code changes and independent tests.",
            "No hourly report should claim improvement when material_delta is false.",
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_rounds(state: dict[str, Any], *, rounds: int, sleep_seconds: float, seed: str, history_path: Path | None = None) -> dict[str, Any]:
    out = deepcopy(state)
    for _ in range(rounds):
        out = evolve_once(out, seed)
        if history_path:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(out["recent"][-1], ensure_ascii=False) + "\n")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("init")
    q.add_argument("--out", required=True)

    q = sub.add_parser("run")
    q.add_argument("--state", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--summary", required=True)
    q.add_argument("--history")
    q.add_argument("--rounds", type=int, default=60)
    q.add_argument("--sleep-seconds", type=float, default=60.0)
    q.add_argument("--seed", default="the-world-ai-foundry-v1")

    args = ap.parse_args()
    if args.cmd == "init":
        write_json(Path(args.out), initial_state())
        return 0

    before = json.loads(Path(args.state).read_text(encoding="utf-8"))
    after = run_rounds(
        before,
        rounds=max(1, args.rounds),
        sleep_seconds=max(0.0, args.sleep_seconds),
        seed=args.seed,
        history_path=Path(args.history) if args.history else None,
    )
    write_json(Path(args.out), after)
    write_json(Path(args.summary), build_hourly_summary(before, after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
