"""Bridge authority-candidate council dossiers into the shared improvement task stream."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

BRIDGE_SCHEMA = "the-world-authority-candidate-improvement-bridge/v1"
SHARED_WITH = ("META", "X", "SENJU", "CHILD", "AI", "PR-ARMY")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task(row: Mapping[str, Any]) -> dict[str, Any]:
    host = str(row.get("host", "candidate"))
    status = str(row.get("status", "unknown_root_evidence_search"))
    hard = bool(row.get("hard_denial_seen", False))
    if status == "hard_deny_reconsideration_ready":
        kind = "hard_deny_reconsideration_request"
        summary = f"Route {host} through independent HARD_DENY reconsideration with changed quorum evidence"
        priority = 94
        capabilities = [
            "authority.evidence.compare",
            "authority.review.request",
            "authority.recheck",
            "authority.opportunity.prioritize",
            "knowledge.share",
            "audit.write",
        ]
    elif status == "unknown_root_review_ready":
        kind = "unknown_root_review_request"
        summary = f"Route unknown-root candidate {host} to existing trusted authority review"
        priority = 86
        capabilities = [
            "authority.candidate.read",
            "authority.evidence.compare",
            "authority.review.request",
            "authority.opportunity.prioritize",
            "knowledge.share",
            "audit.write",
        ]
    elif status == "terminal_stop_requires_owner_reactivation":
        kind = "terminal_stop_evidence_record"
        summary = f"Preserve terminal-stop dossier for {host}; await owner reactivation"
        priority = 96
        capabilities = [
            "authority.candidate.read",
            "authority.evidence.compare",
            "knowledge.share",
            "audit.write",
        ]
    else:
        kind = "unknown_root_evidence_collection"
        summary = f"Collect independent evidence for authority candidate {host}"
        priority = 76 if hard else 66
        capabilities = [
            "authority.candidate.read",
            "authority.evidence.collect",
            "authority.evidence.compare",
            "authority.review.request",
            "authority.opportunity.prioritize",
            "knowledge.share",
        ]

    base = {
        "kind": kind,
        "summary": summary,
        "source": "authority_candidate_council.json",
        "target": host,
        "capabilities": capabilities,
        "priority": priority,
        "authority_required": False,
        "shared_with": list(SHARED_WITH),
        "auto_executable": True,
        "may_create_new_authority_root": False,
        "may_override_hard_denial_by_identity": False,
        "metadata": {
            "council_status": status,
            "hard_denial_seen": hard,
            "evidence_quorum": bool(row.get("evidence_quorum", False)),
            "independent_evidence_count": int(row.get("independent_evidence_count", 0) or 0),
            "authority_changed_since_denial": bool(row.get("authority_changed_since_denial", False)),
        },
    }
    base["task_id"] = f"improve:candidate:{_fingerprint(base)[:18]}"
    return base


def bridge_candidate_council_to_improvement_bus(state_dir: str | Path) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    council = _load(state / "authority_candidate_council.json", {})
    dossiers = council.get("dossiers", []) if isinstance(council, Mapping) else []
    task_path = state / "authority_improvement_tasks.json"
    task_doc = _load(task_path, {})
    prior = task_doc.get("tasks", []) if isinstance(task_doc, Mapping) else []
    prior_by_id = {
        str(row.get("task_id")): dict(row)
        for row in prior if isinstance(row, Mapping) and row.get("task_id")
    }

    added = 0
    updated = 0
    for raw in dossiers if isinstance(dossiers, list) else []:
        if not isinstance(raw, Mapping):
            continue
        task = _task(raw)
        task_id = str(task["task_id"])
        previous = prior_by_id.get(task_id)
        if previous is None:
            task["seen_count"] = 1
            task["first_seen"] = now
            added += 1
        else:
            task["seen_count"] = int(previous.get("seen_count", 0) or 0) + 1
            task["first_seen"] = int(previous.get("first_seen", now) or now)
            task["priority"] = min(100, int(task["priority"]) + min(8, task["seen_count"] - 1))
            updated += 1
        task["last_seen"] = now
        prior_by_id[task_id] = task

    ordered = sorted(prior_by_id.values(), key=lambda row: (-int(row.get("priority", 0)), str(row.get("task_id", ""))))
    generation = int(task_doc.get("generation", 0) or 0) + 1 if isinstance(task_doc, Mapping) else 1
    merged_doc = dict(task_doc) if isinstance(task_doc, Mapping) else {}
    merged_doc.update(
        {
            "schema": merged_doc.get("schema", "the-world-authority-improvement-tasks/v1"),
            "generated_at": now,
            "generation": generation,
            "shared_with": list(SHARED_WITH),
            "tasks": ordered,
            "task_count": len(ordered),
            "candidate_council_connected": True,
            "candidate_council_authority_effect": "none_until_existing_trusted_reviewer_accepts",
        }
    )
    task_path.write_text(json.dumps(merged_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = {
        "schema": BRIDGE_SCHEMA,
        "generated_at": now,
        "candidate_count": len(dossiers) if isinstance(dossiers, list) else 0,
        "tasks_added": added,
        "tasks_updated": updated,
        "total_improvement_tasks": len(ordered),
        "shared_with": list(SHARED_WITH),
        "continuous_improvement": True,
        "new_unrelated_root_self_mint": False,
        "hard_deny_identity_bypass": False,
    }
    (state / "authority_candidate_improvement_bridge.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
