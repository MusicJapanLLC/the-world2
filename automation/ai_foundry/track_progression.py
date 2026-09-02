#!/usr/bin/env python3
"""Evidence-gated AI development track progression.

This controller changes research priority only. It cannot weaken behavioral,
security, permission, regression, or promotion gates and it never turns a BUILDING
engineering capability into VERIFIED merely because research advances.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

AI_MISSION_PREFIX = "RND-AI-DEVELOPMENT"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _ai_mission(queue: dict[str, Any]) -> dict[str, Any] | None:
    rows = [x for x in (queue.get("active") or []) if isinstance(x, dict)]
    candidates = [x for x in rows if str(x.get("research_id") or "").startswith(AI_MISSION_PREFIX)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: int(x.get("priority") or 0), reverse=True)[0]


def _track_ids(program: dict[str, Any]) -> set[str]:
    return {str(x.get("id")) for x in (program.get("tracks") or []) if isinstance(x, dict) and x.get("id")}


def evaluate_progression(
    summary: dict[str, Any],
    program: dict[str, Any],
    queue: dict[str, Any],
) -> dict[str, Any]:
    mission = _ai_mission(queue)
    if not mission:
        return {
            "schema": "the-world-ai-track-progression/v1",
            "decision": "HOLD",
            "reason": "no_ai_development_mission",
            "authority": "priority_only",
            "owner_action": "NONE",
        }

    current = str(mission.get("preferred_track_id") or "AI-DEV-001")
    tracks = _track_ids(program)
    result: dict[str, Any] = {
        "schema": "the-world-ai-track-progression/v1",
        "decision": "HOLD",
        "current_track": current,
        "next_parallel_track": None,
        "reason": "no_progression_rule_satisfied",
        "authority": "priority_only",
        "keep_current_track_active": True,
        "claim_status": "BUILDING",
        "owner_action": "NONE",
        "source_fingerprint": summary.get("report_fingerprint"),
        "gates_unchanged": True,
    }

    # AI-DEV-002 is persistent memory and should continue operating after the next
    # research lane opens. The rule below only opens AI-DEV-003 in parallel once
    # runtime evidence proves that memory is recording AND avoiding recurrence
    # without regressing the behavioral fixture suite.
    if current == "AI-DEV-002" and "AI-DEV-003" in tracks:
        memory = summary.get("failure_memory") if isinstance(summary.get("failure_memory"), dict) else {}
        memory_delta = summary.get("failure_memory_delta") if isinstance(summary.get("failure_memory_delta"), dict) else {}
        fixture_delta = summary.get("strategy_fixture_delta") if isinstance(summary.get("strategy_fixture_delta"), dict) else {}
        regressions = fixture_delta.get("regressed_cases") or []
        active_entries = int(memory.get("active_entries") or 0)
        recorded_total = int(memory.get("recorded_failures") or 0)
        avoided_total = int(memory.get("avoided_recurrences") or 0)
        recorded_delta = int(memory_delta.get("recorded_failures") or 0)
        avoided_delta = int(memory_delta.get("avoided_recurrences") or 0)
        max_entries = 128
        conditions = {
            "summary_v4_or_newer": str(summary.get("schema") or "").startswith("the-world-ai-foundry-hourly/v4"),
            "failure_memory_present": str(memory.get("schema") or "") == "the-world-ai-failure-memory/v1",
            "runtime_failure_observed": recorded_total >= 2 and recorded_delta >= 1,
            "runtime_recurrence_avoided": avoided_total >= 1 and avoided_delta >= 1,
            "memory_bounded": 0 <= active_entries <= max_entries,
            "no_behavioral_regression": len(regressions) == 0,
        }
        result["conditions"] = conditions
        result["runtime_evidence"] = {
            "recorded_failures_total": recorded_total,
            "recorded_failures_delta": recorded_delta,
            "avoided_recurrences_total": avoided_total,
            "avoided_recurrences_delta": avoided_delta,
            "active_entries": active_entries,
            "regressed_cases": regressions,
        }
        if all(conditions.values()):
            result.update({
                "decision": "OPEN_PARALLEL_TRACK",
                "next_parallel_track": "AI-DEV-003",
                "reason": "failure_memory_runtime_parallel_ready_v1",
                "keep_current_track_active": True,
                "claim_status": "BUILDING",
            })

    return result


def apply_progression(queue: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(queue)
    if decision.get("decision") != "OPEN_PARALLEL_TRACK":
        return out
    target = str(decision.get("next_parallel_track") or "")
    if target != "AI-DEV-003":
        return out
    for row in out.get("active") or []:
        if not isinstance(row, dict):
            continue
        if not str(row.get("research_id") or "").startswith(AI_MISSION_PREFIX):
            continue
        if str(row.get("preferred_track_id") or "") != "AI-DEV-002":
            continue
        row["previous_track_id"] = "AI-DEV-002"
        row["preferred_track_id"] = "AI-DEV-003"
        row["current_phase"] = "multi_agent_specialist_league_with_persistent_failure_memory"
        row["progression_rule"] = "failure_memory_runtime_parallel_ready_v1"
        row["failure_memory_continues"] = True
        row["progression_source_fingerprint"] = decision.get("source_fingerprint")
        break
    return out


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--summary", required=True)
    p.add_argument("--program", required=True)
    p.add_argument("--queue", required=True)
    p.add_argument("--decision-out", required=True)
    p.add_argument("--queue-out")
    args = p.parse_args()

    summary = load_json(Path(args.summary))
    program = load_json(Path(args.program))
    queue = load_json(Path(args.queue))
    decision = evaluate_progression(summary, program, queue)
    write_json(Path(args.decision_out), decision)
    if args.queue_out:
        write_json(Path(args.queue_out), apply_progression(queue, decision))
    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
