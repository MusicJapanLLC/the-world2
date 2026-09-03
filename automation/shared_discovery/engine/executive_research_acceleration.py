"""Proposal-only acceleration for META/X/SENJU formal-review research.

This layer increases research throughput and formal-review prioritization without
changing external Authority, credentials, network scope, or terminal controls.
Owner/standing evidence has exactly zero admission/priority weight here.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from engine.authority_approval_constitution import (
    EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER,
    EXECUTIVE_RESEARCH_CAPACITY_MULTIPLIER,
    OWNER_FORMAL_REVIEW_ADMISSION_WEIGHT,
    OWNER_FORMAL_REVIEW_PRIORITY_WEIGHT,
    PRIMARY_APPROVERS,
    constitutional_metadata,
    filter_canonical_review_packets,
)

SCHEMA = "the-world-executive-research-acceleration/v1"
TASK_SCHEMA = "the-world-executive-research-tasks/v1"
PRIORITY_SCHEMA = "the-world-executive-review-priority-queue/v1"
BASELINE_TACTICS_PER_EXECUTIVE = 7
ADDITIONAL_TACTICS = (
    "cross_source_disconfirmation_sprint",
    "bounded_implementation_experiment_design",
)
TARGET_LOOP_MINUTES = 4
MAX_TASKS = 8192


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _host(value: object) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _terminal(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("terminal_stop") is True
        or row.get("hard_deny") is True
        or row.get("revoked") is True
        or row.get("may_bypass_terminal_stop") is True
    )


def _source_candidates(state: Path) -> tuple[list[dict[str, Any]], int]:
    formal = _load(state / "formal_root_authority_approval_queue.json", {})
    rows = formal.get("candidates", ()) if isinstance(formal, Mapping) else ()
    if isinstance(rows, list) and rows:
        return [dict(row) for row in rows if isinstance(row, Mapping)], 0

    review = _load(state / "owner_root_authority_review_packets.json", {})
    raw = review.get("packets", ()) if isinstance(review, Mapping) else ()
    if not isinstance(raw, list):
        return [], 0
    canonical, excluded = filter_canonical_review_packets(
        row for row in raw if isinstance(row, Mapping)
    )
    return canonical, excluded


def _priority(row: Mapping[str, Any]) -> int:
    readiness = max(0, min(_int(row.get("readiness_score")), 100))
    attempts = max(0, min(_int(row.get("attempt_count")), 20))
    # Executive judgment changes formal-review ordering only. Owner evidence is absent
    # from this calculation by construction.
    weighted = round(readiness * EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER)
    return max(0, min(weighted + attempts, 170))


def run_executive_research_acceleration(
    state_dir: str | Path,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    candidates, excluded_noncanonical = _source_candidates(state)

    enriched: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    terminal_excluded = 0

    for raw in candidates:
        if _terminal(raw):
            terminal_excluded += 1
            continue
        host = _host(raw.get("host"))
        if not host:
            continue

        row = dict(raw)
        row.update({
            "host": host,
            "formal_intake_eligible": True,
            "formal_intake_requires_secondary_owner_or_standing_evidence": False,
            "owner_formal_review_admission_weight": OWNER_FORMAL_REVIEW_ADMISSION_WEIGHT,
            "owner_formal_review_priority_weight": OWNER_FORMAL_REVIEW_PRIORITY_WEIGHT,
            "executive_research_capacity_multiplier": EXECUTIVE_RESEARCH_CAPACITY_MULTIPLIER,
            "executive_formal_review_influence_multiplier": EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER,
            "executive_priority_score": _priority(raw),
            "required_approvers": list(PRIMARY_APPROVERS),
            "required_approval": "META_X_SENJU_3_of_3",
            "authority_effect": "none",
            "authority_activated": False,
        })
        enriched.append(row)

        attempt = _int(raw.get("attempt_count"))
        for actor in PRIMARY_APPROVERS:
            for tactic in ADDITIONAL_TACTICS:
                tasks.append({
                    "task_id": f"exec-accel:{host}:{attempt}:{actor.lower()}:{tactic}",
                    "actor": actor,
                    "host": host,
                    "attempt_count": attempt,
                    "tactic": tactic,
                    "status": "pending",
                    "mission": "improve the formal review dossier through research, disconfirmation, and bounded experiment design",
                    "formal_review_only": True,
                    "may_change_external_authority": False,
                    "may_mint_credentials": False,
                    "may_perform_network_io": False,
                    "may_bypass_hard_deny_or_revocation": False,
                })

    enriched.sort(
        key=lambda row: (
            -_int(row.get("executive_priority_score")),
            -_int(row.get("attempt_count")),
            _host(row.get("host")),
        )
    )
    tasks = tasks[:MAX_TASKS]

    prior_queue = _load(state / "formal_root_authority_approval_queue.json", {})
    capacity = _int(prior_queue.get("capacity") if isinstance(prior_queue, Mapping) else 1280, 1280)
    enriched = enriched[:max(1, capacity)]
    constitution = constitutional_metadata()

    formal_queue = dict(prior_queue) if isinstance(prior_queue, Mapping) else {}
    formal_queue.update({
        "schema": str(formal_queue.get("schema") or "the-world-formal-root-authority-approval-queue/v1"),
        "generated_at": current,
        "constitution": constitution,
        "required_approvers": list(PRIMARY_APPROVERS),
        "required_approval": "META_X_SENJU_3_of_3",
        "candidate_count": len(enriched),
        "capacity": max(1, capacity),
        "candidates": enriched,
        "executive_acceleration": {
            "research_capacity_multiplier": EXECUTIVE_RESEARCH_CAPACITY_MULTIPLIER,
            "formal_review_influence_multiplier": EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER,
            "owner_formal_review_admission_weight": OWNER_FORMAL_REVIEW_ADMISSION_WEIGHT,
            "owner_formal_review_priority_weight": OWNER_FORMAL_REVIEW_PRIORITY_WEIGHT,
            "target_loop_minutes": TARGET_LOOP_MINUTES,
        },
        "authority_effect": "none",
        "authority_activated": False,
    })
    _write(state / "formal_root_authority_approval_queue.json", formal_queue)

    _write(state / "executive_review_priority_queue.json", {
        "schema": PRIORITY_SCHEMA,
        "generated_at": current,
        "actors": list(PRIMARY_APPROVERS),
        "influence_multiplier": EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER,
        "owner_admission_weight": OWNER_FORMAL_REVIEW_ADMISSION_WEIGHT,
        "owner_priority_weight": OWNER_FORMAL_REVIEW_PRIORITY_WEIGHT,
        "candidates": enriched,
        "authority_effect": "none",
    })
    _write(state / "executive_research_tasks.json", {
        "schema": TASK_SCHEMA,
        "generated_at": current,
        "actors": list(PRIMARY_APPROVERS),
        "baseline_tactics_per_executive": BASELINE_TACTICS_PER_EXECUTIVE,
        "additional_tactics_per_executive": len(ADDITIONAL_TACTICS),
        "effective_tactic_multiplier": (BASELINE_TACTICS_PER_EXECUTIVE + len(ADDITIONAL_TACTICS)) / BASELINE_TACTICS_PER_EXECUTIVE,
        "research_capacity_multiplier": EXECUTIVE_RESEARCH_CAPACITY_MULTIPLIER,
        "task_count": len(tasks),
        "tasks": tasks,
        "external_side_effects": False,
        "authority_effect": "none",
    })

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "executive_actors": list(PRIMARY_APPROVERS),
        "candidate_count": len(enriched),
        "research_task_count": len(tasks),
        "research_capacity_multiplier": EXECUTIVE_RESEARCH_CAPACITY_MULTIPLIER,
        "effective_tactic_multiplier": (BASELINE_TACTICS_PER_EXECUTIVE + len(ADDITIONAL_TACTICS)) / BASELINE_TACTICS_PER_EXECUTIVE,
        "formal_review_influence_multiplier": EXECUTIVE_FORMAL_REVIEW_INFLUENCE_MULTIPLIER,
        "target_loop_minutes": TARGET_LOOP_MINUTES,
        "owner_formal_review_admission_weight": OWNER_FORMAL_REVIEW_ADMISSION_WEIGHT,
        "owner_formal_review_priority_weight": OWNER_FORMAL_REVIEW_PRIORITY_WEIGHT,
        "secondary_owner_or_standing_evidence_required_for_formal_intake": False,
        "excluded_noncanonical_count": excluded_noncanonical,
        "terminal_excluded_count": terminal_excluded,
        "authority_effect": "none",
        "authority_activated": False,
        "external_side_effects": False,
    }
    _write(state / "executive_research_acceleration_result.json", result)
    return result
