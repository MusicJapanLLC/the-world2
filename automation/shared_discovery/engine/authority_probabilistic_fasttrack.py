"""Recurring probabilistic fast-track for unresolved authority candidates.

A persistent candidate gets a bounded 5% chance every 10-minute bucket to receive
maximum review attention from META/X/SENJU/CHILD/PR-ARMY. A successful draw creates a
formal authority-transition review request through the existing approval machinery.

To make the lane only slightly more active, 10% of fast-tracked candidates receive one
additional independent reviewer cross-check. Neither draw directly creates Authority,
changes a denial to ALLOW, or reactivates a terminal stop.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "the-world-authority-probabilistic-fasttrack/v2"
QUEUE_SCHEMA = "the-world-authority-priority-review-queue/v2"
FAST_TRACK_PERCENT = 5
EXTRA_REVIEW_PERCENT = 10
BUCKET_SECONDS = 600
SHARED_WITH = ("META", "X", "SENJU", "CHILD", "PR-ARMY")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def draw_for(host: str, bucket: int) -> int:
    raw = f"{host.lower().strip()}:{bucket}:authority-review-fasttrack-v2".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % 100


def extra_review_draw_for(host: str, bucket: int) -> int:
    raw = f"{host.lower().strip()}:{bucket}:authority-review-secondary-v1".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % 100


def run_probabilistic_fasttrack(
    state_dir: str | Path,
    *,
    now: int | None = None,
    percent: int = FAST_TRACK_PERCENT,
    extra_review_percent: int = EXTRA_REVIEW_PERCENT,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    probability = max(1, min(int(percent), 5))
    extra_probability = max(0, min(int(extra_review_percent), 10))
    bucket = current // BUCKET_SECONDS
    council = _load(state / "authority_candidate_council.json", {})
    dossiers = council.get("dossiers", []) if isinstance(council, Mapping) else []
    if not isinstance(dossiers, list):
        dossiers = []

    hits: list[dict[str, Any]] = []
    evaluated = 0
    secondary_crosschecks = 0
    for raw in dossiers:
        if not isinstance(raw, Mapping):
            continue
        host = str(raw.get("host") or "").strip().lower()
        if not host or bool(raw.get("terminal_stop", False)):
            continue
        evaluated += 1
        draw = draw_for(host, bucket)
        if draw >= probability:
            continue

        secondary_draw = extra_review_draw_for(host, bucket)
        secondary_crosscheck = secondary_draw < extra_probability
        next_actions = [
            "submit_authority_transition_request_to_existing_review",
            "collect_additional_independent_authority_evidence",
            "rebuild_candidate_dossier",
            "request_meta_x_senju_pr_army_revote",
            "request_independent_authority_review",
            "generate_owner_verification_packet",
            "recheck_when_authority_evidence_changes",
        ]
        if secondary_crosscheck:
            secondary_crosschecks += 1
            next_actions.append("request_secondary_independent_reviewer_crosscheck")

        hits.append({
            "host": host,
            "url": raw.get("url"),
            "source_status": raw.get("status"),
            "draw": draw,
            "threshold_percent": probability,
            "priority": 100,
            "shared_with": list(SHARED_WITH),
            "autonomous_next_actions": next_actions,
            "authority_transition_requested": True,
            "secondary_review_crosscheck": secondary_crosscheck,
            "secondary_review_draw": secondary_draw,
            "secondary_review_threshold_percent": extra_probability,
            "authority_effect": "formal_authority_transition_request_requires_existing_approval",
            "may_self_mint_new_root": False,
            "may_override_hard_deny": False,
        })

    queue = {
        "schema": QUEUE_SCHEMA,
        "generated_at": current,
        "mode": "five_percent_recurring_authority_transition_fasttrack",
        "probability_percent_per_bucket": probability,
        "extra_review_percent_on_fasttrack": extra_probability,
        "bucket_seconds": BUCKET_SECONDS,
        "shared_with": list(SHARED_WITH),
        "request_count": len(hits),
        "secondary_review_crosscheck_count": secondary_crosschecks,
        "requests": hits,
        "authority_effect": "formal_transition_request_until_existing_authority_review_approves",
    }
    (state / "authority_priority_review_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "probability_percent_per_bucket": probability,
        "extra_review_percent_on_fasttrack": extra_probability,
        "bucket_seconds": BUCKET_SECONDS,
        "evaluated_candidates": evaluated,
        "fast_track_count": len(hits),
        "authority_transition_requests_created": len(hits),
        "secondary_review_crosscheck_count": secondary_crosschecks,
        "persistent_candidates_receive_new_chance_each_bucket": True,
        "new_root_self_mint": False,
        "hard_deny_identity_bypass": False,
        "terminal_stop_lottery_bypass": False,
    }
    (state / "authority_probabilistic_fasttrack.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return result
