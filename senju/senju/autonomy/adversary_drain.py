"""Drain every queued real-surface adversary feedback item through Senju.

The adversary pressure loop records controlled fail-closed availability effects
one-by-one in Senju's real AutonomyQueue. CI uses temporary state, so this
module exhausts every bounded ``real_surface_followup`` item before the run
ends instead of leaving feedback stranded in an ephemeral queue.

No network authority is added here. Each feedback item is executed through the
real ``AutonomyEngine`` and the repository-local real-surface harness, whose
final external transport seam remains inert during adversarial regression.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any

from .engine import AutonomyEngine


def drain_adversary_feedback(
    state_dir: str | Path,
    *,
    max_cycles: int = 512,
) -> dict[str, Any]:
    if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or not 1 <= max_cycles <= 2048:
        raise ValueError("max_cycles must be an integer between 1 and 2048")

    engine = AutonomyEngine(state_dir)
    consumed: list[dict[str, Any]] = []

    for _ in range(max_cycles):
        # Feedback items cost 20; the normal seeded tournament items cost
        # hundreds, so this budget selects only the bounded adversary-feedback
        # lane and stops automatically when that lane is empty.
        result = engine.execute_next_cycle(max_matches=20)
        if result is None:
            break
        consumed.append(dataclasses.asdict(result))

    pending_feedback = [
        item.to_dict()
        for item in engine.queue._items.values()
        if item.parameters.get("runner") == "real_surface_followup"
        and item.status in {"pending", "failed", "in_progress"}
    ]
    completed_feedback = [
        item.to_dict()
        for item in engine.queue._items.values()
        if item.parameters.get("runner") == "real_surface_followup"
        and item.status == "completed"
    ]

    return {
        "schema": "senju-adversary-feedback-drain/v1",
        "state_dir": str(engine.state_dir),
        "drained_cycles": len(consumed),
        "completed_feedback_items": len(completed_feedback),
        "pending_feedback_items": len(pending_feedback),
        "fully_drained": len(pending_feedback) == 0,
        "consumed": consumed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--max-cycles", type=int, default=512)
    parser.add_argument("--json", dest="output", type=Path)
    args = parser.parse_args(argv)

    payload = drain_adversary_feedback(args.state_dir, max_cycles=args.max_cycles)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["fully_drained"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
