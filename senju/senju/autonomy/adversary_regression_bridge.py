"""Bridge genuine real-surface probe regressions into Senju's main autonomy queue.

The normal adversary loop streams successful fail-closed guard effects as they are
observed. This module handles the opposite case: a probe that *fails* its expected
contract. Each failed probe is recorded as a regression-tripwire event and queued
onto the real AutonomyEngine for a bounded repository-local follow-up before CI
fails closed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from .engine import AutonomyEngine
from .queue import WorkItem


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return raw


def _failed_rows(cycle_report: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    rounds = cycle_report.get("round_reports", [])
    if not isinstance(rounds, list):
        return failures
    for round_report in rounds:
        if not isinstance(round_report, dict):
            continue
        round_index = round_report.get("pressure_round", 0)
        rows = round_report.get("results", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("passed") is True:
                continue
            annotated = dict(row)
            annotated["pressure_round"] = round_index
            failures.append(annotated)
    return failures


def _event_id(cycle_id: str, row: dict[str, Any]) -> str:
    payload = "|".join(
        [
            cycle_id,
            str(row.get("pressure_round", "")),
            str(row.get("target", "unknown")),
            str(row.get("name", "unknown")),
            str(row.get("detail", "")),
        ]
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def bridge_regressions(
    *,
    state_dir: Path,
    summary_path: Path,
) -> dict[str, Any]:
    summary = _load_json(summary_path)
    engine = AutonomyEngine(state_dir)
    event_dir = state_dir / "autonomy_reports" / "real_surface_adversary"
    event_dir.mkdir(parents=True, exist_ok=True)
    event_log = event_dir / "regression_tripwires.jsonl"

    events: list[dict[str, Any]] = []
    queued: list[str] = []
    cycles = summary.get("cycles", [])
    if not isinstance(cycles, list):
        cycles = []

    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        report_raw = cycle.get("report_path", "")
        if not isinstance(report_raw, str) or not report_raw:
            continue
        report_path = Path(report_raw)
        if not report_path.is_file():
            continue
        cycle_report = _load_json(report_path)
        cycle_id = str(cycle.get("item_id", cycle_report.get("item_id", "unknown-cycle")))

        for row in _failed_rows(cycle_report):
            event_id = _event_id(cycle_id, row)
            target = str(row.get("target", "unknown"))
            probe = str(row.get("name", "unknown"))
            detail = str(row.get("detail", ""))
            event = {
                "schema": "senju-adversary-regression/v1",
                "event_id": event_id,
                "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "pressure_item_id": cycle_id,
                "pressure_round": row.get("pressure_round", 0),
                "target": target,
                "probe": probe,
                "observed_effect": "real-surface-regression",
                "effect_class": "regression-tripwire",
                "guard_outcome": "contract-failed",
                "detail": detail,
            }
            events.append(event)

            item = WorkItem(
                item_id=f"adv-regression-{event_id}",
                hypothesis=(
                    f"Real-surface adversary probe {target}/{probe} violated its expected contract; "
                    "Senju must reproduce the exact probe and keep pressure on that surface"
                ),
                category="red_team",
                expected_value=1.0,
                cost_budget_matches=20,
                runtime_seconds_budget=240.0,
                max_retries=3,
                authority_scope="none",
                prerequisite_evidence=[event_id],
                parameters={
                    "runner": "real_surface_followup",
                    "focus_target": target,
                    "focus_probe": probe,
                    "focus_family": "",
                    "source_effect_id": event_id,
                    "observed_effect": "real-surface-regression",
                    "regression_tripwire": True,
                    "feedback_depth": 0,
                },
            )
            if engine.queue.enqueue(item):
                queued.append(item.item_id)

    if events:
        with event_log.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "schema": "senju-adversary-regression-bridge/v1",
        "summary_path": str(summary_path),
        "state_dir": str(state_dir),
        "regression_events": len(events),
        "senju_regression_items_queued": len(queued),
        "queued_item_ids": queued,
        "event_log_path": str(event_log),
        "all_regressions_shared": len(events) == len(queued),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--json", dest="output", type=Path)
    args = parser.parse_args(argv)

    result = bridge_regressions(state_dir=args.state_dir, summary_path=args.summary)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["all_regressions_shared"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
