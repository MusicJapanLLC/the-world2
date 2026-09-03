"""Canonical case lifecycle for negotiation-vetted Authority review.

Flow:
    formal negotiation-vetted case
      -> independent case inspection
      -> META/X/SENJU 3/3 executive approval
      -> parliamentary review queue

Case-clock rules:
- an unprocessed case expires after 3 days;
- an expired case that remains non-terminal for 7 more days is forced into
  high-priority reconsideration;
- elapsed time never creates Authority and never counts as approval.

This module only moves review state. It cannot mint Authority, credentials, network
access, or bypass HARD_DENY/revocation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from engine.authority_approval_constitution import (
    ALL_PARTICIPANTS,
    CANONICAL_FLOW_ID,
    CONSTITUTION_ID,
    PRIMARY_APPROVERS,
    constitutional_metadata,
    is_canonical_review_packet,
)

SCHEMA = "the-world-authority-case-lifecycle/v1"
STATE_SCHEMA = "the-world-authority-case-lifecycle-state/v1"
PARLIAMENT_SCHEMA = "the-world-parliamentary-authority-review-queue/v1"
RECONSIDERATION_SCHEMA = "the-world-authority-case-reconsideration-queue/v1"
BROADCAST_SCHEMA = "the-world-authority-case-lifecycle-broadcast/v1"
EXECUTIVE_DECISIONS_SCHEMA = "the-world-executive-authority-decisions/v1"
INSPECTOR_RESULTS_SCHEMA = "the-world-authority-case-inspector-results/v1"

UNPROCESSED_EXPIRY_SECONDS = 3 * 24 * 60 * 60
EXPIRED_RECONSIDERATION_SECONDS = 7 * 24 * 60 * 60


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
    status = str(row.get("status") or "").strip().lower()
    return bool(
        row.get("terminal_stop") is True
        or row.get("hard_deny") is True
        or row.get("revoked") is True
        or status in {"terminal_stop", "revoked", "hard_deny"}
    )


def _inspector_index(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load(state / "authority_case_inspector_results.json", {})
    if not isinstance(doc, Mapping):
        return {}
    if str(doc.get("schema") or INSPECTOR_RESULTS_SCHEMA) != INSPECTOR_RESULTS_SCHEMA:
        return {}
    rows = doc.get("results", doc.get("decisions", ()))
    if not isinstance(rows, list):
        return {}
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if host:
            out[host] = row
    return out


def _structural_inspection(packet: Mapping[str, Any], external: Mapping[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    if not is_canonical_review_packet(packet):
        reasons.append("noncanonical_packet")
    if not _host(packet.get("host")):
        reasons.append("missing_host")
    if _terminal(packet):
        reasons.append("terminal_or_revoked")
    if packet.get("authority_effect") != "none":
        reasons.append("unexpected_authority_effect")

    external_status = ""
    if isinstance(external, Mapping):
        external_status = str(external.get("status") or external.get("decision") or "").strip().lower()
        if external_status in {"reject", "rejected", "hold", "blocked", "fail", "failed"}:
            reasons.append("independent_inspector_hold")
        if _terminal(external):
            reasons.append("independent_inspector_terminal")

    return {
        "status": "inspection_pass" if not reasons else "inspection_hold",
        "reasons": reasons,
        "inspector": "authority-case-inspector/v1",
        "external_inspector_result_present": isinstance(external, Mapping),
        "external_inspector_status": external_status or None,
        "authority_effect": "none",
    }


def _decision_index(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load(state / "executive_council_decisions.json", {})
    if not isinstance(doc, Mapping):
        return {}
    if str(doc.get("schema") or EXECUTIVE_DECISIONS_SCHEMA) != EXECUTIVE_DECISIONS_SCHEMA:
        return {}
    rows = doc.get("decisions", ())
    if not isinstance(rows, list):
        return {}
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if host:
            out[host] = row
    return out


def _executive_approved(decision: Mapping[str, Any] | None) -> bool:
    if not isinstance(decision, Mapping):
        return False
    approved_by = {str(v).strip().upper() for v in decision.get("approved_by", ()) if str(v).strip()}
    return bool(
        decision.get("approved") is True
        and approved_by == set(PRIMARY_APPROVERS)
        and str(decision.get("constitution_id") or "") == CONSTITUTION_ID
        and str(decision.get("canonical_flow_id") or "") == CANONICAL_FLOW_ID
        and not _terminal(decision)
    )


def run_case_lifecycle(state_dir: str | Path, *, now: int | None = None) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)

    queue_doc = _load(state / "formal_root_authority_approval_queue.json", {})
    raw_cases = queue_doc.get("candidates", ()) if isinstance(queue_doc, Mapping) else ()
    cases = [dict(row) for row in raw_cases if isinstance(row, Mapping)] if isinstance(raw_cases, list) else []

    previous_doc = _load(state / "authority_case_lifecycle_state.json", {})
    previous_rows = previous_doc.get("cases", ()) if isinstance(previous_doc, Mapping) else ()
    previous_by_host = {
        _host(row.get("host")): row
        for row in previous_rows
        if isinstance(row, Mapping) and _host(row.get("host"))
    } if isinstance(previous_rows, list) else {}

    decisions = _decision_index(state)
    inspector_results = _inspector_index(state)
    lifecycle_rows: list[dict[str, Any]] = []
    parliament_rows: list[dict[str, Any]] = []
    reconsideration_rows: list[dict[str, Any]] = []

    for packet in cases:
        host = _host(packet.get("host"))
        if not host:
            continue
        prior = previous_by_host.get(host, {})
        first_seen = _int(prior.get("first_seen_at")) or _int(packet.get("formal_intake_at")) or _int(packet.get("submitted_at")) or current
        expiry_at = first_seen + UNPROCESSED_EXPIRY_SECONDS
        expired_at = _int(prior.get("expired_at"))

        inspection = _structural_inspection(packet, inspector_results.get(host))
        decision = decisions.get(host)
        decision_at = _int(decision.get("decided_at")) if isinstance(decision, Mapping) else 0
        raw_executive_approved = inspection["status"] == "inspection_pass" and _executive_approved(decision)
        decision_was_timely = bool(raw_executive_approved and (current < expiry_at or (decision_at and decision_at <= expiry_at)))
        executive_approved = raw_executive_approved and decision_was_timely
        executive_rejected = bool(isinstance(decision, Mapping) and decision.get("approved") is False)
        terminal = _terminal(packet) or bool(isinstance(decision, Mapping) and _terminal(decision))
        status = "pending_inspection_or_executive_review"

        if terminal:
            status = "terminal_stop"
        elif executive_rejected:
            status = "executive_rejected"
        elif current >= expiry_at and not executive_approved:
            expired_at = expired_at or expiry_at
            if current >= expired_at + EXPIRED_RECONSIDERATION_SECONDS:
                status = "mandatory_reconsideration_due"
                reconsideration_rows.append({
                    "host": host,
                    "case_id": packet.get("packet_id") or packet.get("submission_id"),
                    "expired_at": expired_at,
                    "reconsideration_due_at": expired_at + EXPIRED_RECONSIDERATION_SECONDS,
                    "priority": 100,
                    "required_next_step": "fresh_inspection_and_META_X_SENJU_3_of_3_revote",
                    "late_prior_decision_may_reactivate": False,
                    "time_elapsed_is_approval": False,
                    "authority_effect": "none",
                })
            else:
                status = "expired_unprocessed"
        elif executive_approved:
            status = "elevated_to_parliamentary_review"
            parliament_rows.append({
                "case_id": packet.get("packet_id") or packet.get("submission_id"),
                "host": host,
                "elevated_at": current,
                "inspection": inspection,
                "executive_decision": dict(decision) if isinstance(decision, Mapping) else None,
                "required_upstream_approval": "META_X_SENJU_3_of_3",
                "parliamentary_status": "awaiting_parliamentary_review",
                "constitution_id": CONSTITUTION_ID,
                "canonical_flow_id": CANONICAL_FLOW_ID,
                "authority_effect": "none",
            })

        lifecycle_rows.append({
            "case_id": packet.get("packet_id") or packet.get("submission_id"),
            "host": host,
            "first_seen_at": first_seen,
            "expires_unprocessed_at": expiry_at,
            "expired_at": expired_at or None,
            "status": status,
            "inspection": inspection,
            "executive_decision_present": isinstance(decision, Mapping),
            "executive_decided_at": decision_at or None,
            "executive_approval_was_timely": decision_was_timely,
            "executive_approved": executive_approved,
            "parliamentary_elevation": executive_approved,
            "time_elapsed_is_approval": False,
            "authority_effect": "none",
        })

    constitution = constitutional_metadata()
    state_doc = {
        "schema": STATE_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "unprocessed_expiry_seconds": UNPROCESSED_EXPIRY_SECONDS,
        "expired_reconsideration_seconds": EXPIRED_RECONSIDERATION_SECONDS,
        "case_count": len(lifecycle_rows),
        "cases": lifecycle_rows,
        "authority_effect": "none",
    }
    parliament_doc = {
        "schema": PARLIAMENT_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "entry_requirement": "inspection_pass_then_META_X_SENJU_3_of_3_before_case_expiry",
        "candidate_count": len(parliament_rows),
        "candidates": parliament_rows,
        "authority_effect": "none",
    }
    reconsideration_doc = {
        "schema": RECONSIDERATION_SCHEMA,
        "generated_at": current,
        "rule": "expired cases receive mandatory fresh review after seven days; elapsed time never equals approval",
        "candidate_count": len(reconsideration_rows),
        "candidates": reconsideration_rows,
        "authority_effect": "none",
    }
    broadcast_doc = {
        "schema": BROADCAST_SCHEMA,
        "generated_at": current,
        "shared_with": list(ALL_PARTICIPANTS),
        "binding_case_rules": {
            "inspection_precedes_executive_review": True,
            "executive_approval_required_for_parliamentary_elevation": "META_X_SENJU_3_of_3",
            "executive_approval_must_precede_case_expiry": True,
            "unprocessed_case_expires_after_seconds": UNPROCESSED_EXPIRY_SECONDS,
            "expired_case_reconsideration_after_seconds": EXPIRED_RECONSIDERATION_SECONDS,
            "late_prior_decision_may_reactivate_expired_case": False,
            "elapsed_time_counts_as_approval": False,
        },
        "authority_effect": "none",
    }

    _write(state / "authority_case_lifecycle_state.json", state_doc)
    _write(state / "parliamentary_authority_review_queue.json", parliament_doc)
    _write(state / "authority_case_reconsideration_queue.json", reconsideration_doc)
    _write(state / "authority_case_lifecycle_broadcast.json", broadcast_doc)

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "case_count": len(lifecycle_rows),
        "parliamentary_elevation_count": len(parliament_rows),
        "expired_unprocessed_count": sum(1 for row in lifecycle_rows if row["status"] == "expired_unprocessed"),
        "mandatory_reconsideration_count": len(reconsideration_rows),
        "unprocessed_expiry_seconds": UNPROCESSED_EXPIRY_SECONDS,
        "expired_reconsideration_seconds": EXPIRED_RECONSIDERATION_SECONDS,
        "executive_approval_required": "META_X_SENJU_3_of_3",
        "executive_approval_must_precede_case_expiry": True,
        "time_elapsed_is_approval": False,
        "shared_with": list(ALL_PARTICIPANTS),
        "authority_effect": "none",
        "authority_activated": False,
    }
    _write(state / "authority_case_lifecycle_result.json", result)
    return result
