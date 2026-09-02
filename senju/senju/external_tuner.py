"""Adaptive transport tuning for Senju external contact.

This module changes only resilience parameters (timeout/retries). It never widens
host allowlists, network scopes, HTTP methods, credentials, or redirect policy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_STATE: dict[str, Any] = {
    "schema": "senju-external-transport-strategy/v1",
    "timeout_seconds": 5.0,
    "retries": 2,
    "healthy_streak": 0,
    "degraded_streak": 0,
    "updated_at_utc": None,
    "last_reason": "bootstrap",
}


def _clamp_timeout(value: float) -> float:
    return round(max(3.0, min(float(value), 15.0)), 1)


def _clamp_retries(value: int) -> int:
    return max(0, min(int(value), 3))


def load_state(path: str | Path | None) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    if path and Path(path).exists():
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema") == DEFAULT_STATE["schema"]:
            state.update(raw)
    state["timeout_seconds"] = _clamp_timeout(state["timeout_seconds"])
    state["retries"] = _clamp_retries(state["retries"])
    state["healthy_streak"] = max(0, int(state.get("healthy_streak", 0)))
    state["degraded_streak"] = max(0, int(state.get("degraded_streak", 0)))
    return state


def tune(state: dict[str, Any], receipts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    receipts = list(receipts)
    if not receipts:
        raise ValueError("at least one external-contact receipt is required")

    degraded = any(
        not bool(r.get("provider_acknowledged"))
        or int(r.get("status", 0)) >= 500
        or int(r.get("attempt_count", 1)) > 1
        for r in receipts
    )
    next_state = dict(state)

    if degraded:
        next_state["healthy_streak"] = 0
        next_state["degraded_streak"] = int(state.get("degraded_streak", 0)) + 1
        next_state["timeout_seconds"] = _clamp_timeout(float(state["timeout_seconds"]) + 1.5)
        next_state["retries"] = _clamp_retries(int(state["retries"]) + 1)
        next_state["last_reason"] = "degraded_contact_increase_resilience"
    else:
        streak = int(state.get("healthy_streak", 0)) + 1
        next_state["healthy_streak"] = streak
        next_state["degraded_streak"] = 0
        # After several clean runs, trim latency budget gradually but retain at
        # least one retry. This optimizes without reducing target-scope safety.
        if streak >= 4:
            next_state["timeout_seconds"] = _clamp_timeout(float(state["timeout_seconds"]) - 0.5)
            next_state["retries"] = max(1, _clamp_retries(int(state["retries"])))
            next_state["healthy_streak"] = 0
            next_state["last_reason"] = "sustained_health_reduce_latency_budget"
        else:
            next_state["timeout_seconds"] = _clamp_timeout(float(state["timeout_seconds"]))
            next_state["retries"] = _clamp_retries(int(state["retries"]))
            next_state["last_reason"] = "healthy_hold_strategy"

    next_state["schema"] = DEFAULT_STATE["schema"]
    next_state["updated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return next_state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tune Senju outbound resilience from real receipts")
    p.add_argument("--state")
    p.add_argument("--receipt", action="append", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    state = load_state(args.state)
    receipts = [json.loads(Path(x).read_text(encoding="utf-8")) for x in args.receipt]
    next_state = tune(state, receipts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(next_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(next_state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
