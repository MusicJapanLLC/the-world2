"""Increase new-host/root negotiation throughput through the canonical council-first flow.

All active candidates are routed to META/X/SENJU primary review. Owner/standing evidence
is carried only as rank-3 secondary validation metadata and has no power to admit a
candidate, raise review priority, or override a council rejection.

Packets from approval flows not named by the binding constitution are excluded from the
canonical review surface.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from engine.authority_approval_constitution import (
    ALL_PARTICIPANTS,
    CANONICAL_FLOW_ID,
    CONSTITUTION_ID,
    PRIMARY_APPROVERS,
    canonical_review_packet,
    constitutional_metadata,
    filter_canonical_review_packets,
    is_canonical_review_packet,
)

SCHEMA = "the-world-negotiation-submission-accelerator/v2"
OUTBOX_SCHEMA = "the-world-root-authority-approval-outbox/v2"
REVIEW_SCHEMA = "the-world-council-root-authority-review-packets/v3"
LEDGER_SCHEMA = "the-world-root-authority-submission-ledger/v2"
PEER_FEED_SCHEMA = "the-world-root-negotiation-peer-feed/v2"
QUEUE_SCHEMA = "the-world-authority-opportunity-queue/v1"
APPROVERS = PRIMARY_APPROVERS
COLLABORATORS = ALL_PARTICIPANTS
RESUBMIT_COOLDOWN_SECONDS = 30 * 60
MAX_OUTBOX = 2048
MAX_REVIEW_PACKETS = 2048


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fingerprint(candidate: Mapping[str, Any]) -> str:
    secondary = candidate.get("secondary_validation") if isinstance(candidate.get("secondary_validation"), Mapping) else {}
    body = {
        "host": str(candidate.get("host") or ""),
        "source_files": sorted(str(v) for v in candidate.get("source_files", ()) if str(v)),
        "source_refs": sorted(str(v) for v in candidate.get("source_refs", ()) if str(v)),
        "reasons": sorted(str(v) for v in candidate.get("reasons", ()) if str(v)),
        "readiness_score": int(candidate.get("readiness_score", 0) or 0),
        "secondary_validation_present": bool(secondary.get("present")),
        "secondary_evidence_type": secondary.get("evidence_type"),
        "secondary_evidence_ref": secondary.get("evidence_ref"),
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _submission_reason(previous: Mapping[str, Any] | None, fingerprint: str, now: int) -> str | None:
    if not isinstance(previous, Mapping):
        return "new_candidate"
    if str(previous.get("evidence_fingerprint") or "") != fingerprint:
        return "evidence_changed"
    try:
        last = int(previous.get("last_submitted_at", 0) or 0)
    except (TypeError, ValueError):
        last = 0
    if now - last >= RESUBMIT_COOLDOWN_SECONDS:
        return "cooldown_retry"
    return None


def _review_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    return canonical_review_packet({
        "packet_id": str(packet.get("submission_id") or ""),
        "submission_id": str(packet.get("submission_id") or ""),
        "host": packet.get("host"),
        "candidate_id": packet.get("candidate_id"),
        "attempt_count": packet.get("attempt_count"),
        "submitted_at": packet.get("submitted_at"),
        "submission_reason": packet.get("submission_reason"),
        "agents": list(COLLABORATORS),
        "readiness_score": packet.get("readiness_score"),
        "requested_decision": "META_X_SENJU_approve_or_reject_new_host_root_candidate",
        "secondary_validation": packet.get("secondary_validation"),
        "secondary_owner_or_standing_evidence_is_rank_3": True,
        "may_self_mint_root": False,
        "may_bypass_terminal_stop": False,
    })


def _share_into_opportunity_queue(
    state: Path,
    candidates: list[Mapping[str, Any]],
    ledger: Mapping[str, Any],
    *,
    now: int,
) -> int:
    path = state / "authority_opportunity_queue.json"
    doc = _load(path, {})
    rows = doc.get("opportunities", ()) if isinstance(doc, Mapping) else ()
    by_host: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            host = str(raw.get("host") or "").strip().lower().rstrip(".")
            if host:
                by_host[host] = dict(raw)

    shared = 0
    for candidate in candidates:
        if bool(candidate.get("terminal_stop")):
            continue
        host = str(candidate.get("host") or "").strip().lower().rstrip(".")
        if not host:
            continue
        current = by_host.get(host, {})
        if current.get("hard_deny") is True or current.get("revoked") is True:
            continue
        meta = ledger.get(host, {}) if isinstance(ledger.get(host), Mapping) else {}
        reasons = candidate.get("reasons", ())
        fallback_reason = next((str(v) for v in reasons if str(v).strip()), "Root Authority negotiation candidate")
        try:
            old_priority = int(current.get("priority", 0) or 0)
        except (TypeError, ValueError):
            old_priority = 0
        readiness = max(1, min(int(candidate.get("readiness_score", 0) or 0), 100))
        current.update({
            "host": host,
            "reason": str(current.get("reason") or fallback_reason)[:400],
            "priority": max(old_priority, readiness, 70),
            "source": str(current.get("source") or "root_authority_negotiation"),
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": False,
            "revoked": False,
            "negotiation_attempt_count": int(candidate.get("attempt_count", 0) or 0),
            "approval_submission_count": int(meta.get("submission_count", 0) or 0),
            "last_approval_submission_at": int(meta.get("last_submitted_at", 0) or 0),
            "last_submission_reason": meta.get("last_submission_reason"),
            "approval_flow_requested": int(meta.get("submission_count", 0) or 0) > 0,
            "canonical_approval_flow_id": CANONICAL_FLOW_ID,
            "authority_approval_constitution_id": CONSTITUTION_ID,
            "primary_approvers": list(PRIMARY_APPROVERS),
            "secondary_owner_or_standing_evidence_rank": 3,
            "secondary_evidence_may_raise_review_priority": False,
            "negotiation_shared_with": list(COLLABORATORS),
            "negotiation_peer_feed": "root_negotiation_peer_feed.json",
        })
        by_host[host] = current
        shared += 1

    _write(path, {
        "schema": str(doc.get("schema") or QUEUE_SCHEMA) if isinstance(doc, Mapping) else QUEUE_SCHEMA,
        "generated_at": now,
        "producer": "authority_collaboration_bus+negotiation_submission_accelerator",
        "proposal_only": True,
        "authority_activated": False,
        "external_side_effects": False,
        "constitution": constitutional_metadata(),
        "opportunities": sorted(by_host.values(), key=lambda row: (-int(row.get("priority", 0) or 0), str(row.get("host", "")))),
        "opportunity_count": len(by_host),
    })
    return shared


def run_submission_accelerator(state_dir: str | Path, *, now: int | None = None) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    constitution = constitutional_metadata()

    root_state = _load(state / "root_authority_negotiation_state.json", {})
    raw_candidates = root_state.get("candidates", ()) if isinstance(root_state, Mapping) else ()
    candidates = [row for row in raw_candidates if isinstance(row, Mapping)] if isinstance(raw_candidates, list) else []

    ledger_doc = _load(state / "negotiation_submission_ledger.json", {})
    ledger = ledger_doc.get("by_host", {}) if isinstance(ledger_doc, Mapping) else {}
    if not isinstance(ledger, dict):
        ledger = {}

    old_outbox = _load(state / "root_authority_approval_outbox.json", {})
    old_packets = old_outbox.get("packets", ()) if isinstance(old_outbox, Mapping) else ()
    by_id: dict[str, dict[str, Any]] = {}
    excluded_noncanonical = 0
    if isinstance(old_packets, list):
        for packet in old_packets:
            if not isinstance(packet, Mapping) or not packet.get("submission_id"):
                continue
            if not is_canonical_review_packet(packet):
                excluded_noncanonical += 1
                continue
            by_id[str(packet["submission_id"])] = dict(packet)

    old_review = _load(state / "owner_root_authority_review_packets.json", {})
    old_review_packets = old_review.get("packets", ()) if isinstance(old_review, Mapping) else ()
    canonical_old, excluded_review = filter_canonical_review_packets(
        row for row in old_review_packets if isinstance(row, Mapping)
    ) if isinstance(old_review_packets, list) else ([], 0)
    excluded_noncanonical += excluded_review
    review_by_id: dict[str, dict[str, Any]] = {}
    for packet in canonical_old:
        packet_id = str(packet.get("packet_id") or packet.get("submission_id") or "").strip()
        if packet_id:
            review_by_id[packet_id] = dict(packet)

    submitted: list[dict[str, Any]] = []
    peer_tasks: list[dict[str, Any]] = []
    skipped_cooldown = 0
    terminal_skipped = 0

    for raw in candidates:
        host = str(raw.get("host") or "").strip().lower().rstrip(".")
        if not host:
            continue
        if bool(raw.get("terminal_stop")):
            terminal_skipped += 1
            continue

        fp = _fingerprint(raw)
        reason = _submission_reason(ledger.get(host), fp, current)
        if reason is None:
            skipped_cooldown += 1
        else:
            attempt = int(raw.get("attempt_count", 0) or 0)
            submission_id = hashlib.sha256(f"{host}:{fp}:{current}:{reason}".encode()).hexdigest()[:24]
            packet = canonical_review_packet({
                "submission_id": f"root-approval-{submission_id}",
                "host": host,
                "candidate_id": raw.get("candidate_id"),
                "attempt_count": attempt,
                "submitted_at": current,
                "submission_reason": reason,
                "evidence_fingerprint": fp,
                "readiness_score": int(raw.get("readiness_score", 0) or 0),
                "source_files": list(raw.get("source_files", ()))[:32],
                "source_refs": list(raw.get("source_refs", ()))[:32],
                "secondary_validation": raw.get("secondary_validation"),
                "requested_decision": "META_X_SENJU_approve_or_reject_new_host_root_candidate",
                "shared_with": list(COLLABORATORS),
                "secondary_owner_or_standing_evidence_is_rank_3": True,
                "may_self_mint_root": False,
                "may_bypass_terminal_stop": False,
            })
            by_id[packet["submission_id"]] = packet
            review = _review_packet(packet)
            review_by_id[review["packet_id"]] = review
            submitted.append(packet)
            previous = ledger.get(host, {}) if isinstance(ledger.get(host), Mapping) else {}
            ledger[host] = {
                "host": host,
                "last_submitted_at": current,
                "first_submitted_at": int(previous.get("first_submitted_at", current) or current),
                "submission_count": int(previous.get("submission_count", 0) or 0) + 1,
                "evidence_fingerprint": fp,
                "last_submission_reason": reason,
                "constitution_id": CONSTITUTION_ID,
                "canonical_flow_id": CANONICAL_FLOW_ID,
            }

        for actor in COLLABORATORS:
            peer_tasks.append({
                "task_id": f"negotiation-share:{host}:{int(raw.get('attempt_count', 0) or 0)}:{actor.lower()}",
                "actor": actor,
                "host": host,
                "attempt_count": int(raw.get("attempt_count", 0) or 0),
                "mission": "share fresh candidate evidence and route a complete case into META/X/SENJU primary review",
                "approval_submission_is_goal": True,
                "approval_stage": "executive_council_primary_review",
                "primary_approvers": list(PRIMARY_APPROVERS),
                "secondary_owner_or_standing_evidence_is_post_council": True,
                "share_across_pr_agents": True,
                "constitution_id": CONSTITUTION_ID,
                "canonical_flow_id": CANONICAL_FLOW_ID,
                "authority_effect": "none",
            })

    packets = sorted(by_id.values(), key=lambda row: int(row.get("submitted_at", 0) or 0), reverse=True)[:MAX_OUTBOX]
    review_packets = sorted(
        review_by_id.values(),
        key=lambda row: int(row.get("submitted_at", 0) or 0),
        reverse=True,
    )[:MAX_REVIEW_PACKETS]
    shared_count = _share_into_opportunity_queue(state, candidates, ledger, now=current)

    _write(state / "root_authority_approval_outbox.json", {
        "schema": OUTBOX_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "required_approvers": list(APPROVERS),
        "packet_count": len(packets),
        "new_submissions_this_cycle": len(submitted),
        "excluded_noncanonical_packet_count": excluded_noncanonical,
        "packets": packets,
        "authority_effect": "none",
    })
    _write(state / "owner_root_authority_review_packets.json", {
        "schema": REVIEW_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "submission_accelerator_enabled": True,
        "required_approvers": list(APPROVERS),
        "packet_count": len(review_packets),
        "new_submissions_this_cycle": len(submitted),
        "excluded_noncanonical_packet_count": excluded_noncanonical,
        "unlisted_flow_policy": "exclude_from_canonical_review_surface",
        "packets": review_packets,
        "authority_effect": "none",
    })
    _write(state / "negotiation_submission_ledger.json", {
        "schema": LEDGER_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "resubmit_cooldown_seconds": RESUBMIT_COOLDOWN_SECONDS,
        "by_host": ledger,
    })
    _write(state / "root_negotiation_peer_feed.json", {
        "schema": PEER_FEED_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "collaborators": list(COLLABORATORS),
        "task_count": len(peer_tasks),
        "tasks": peer_tasks,
        "goal": "increase canonical META/X/SENJU primary-review submissions and cross-AI evidence sharing",
        "authority_effect": "none",
    })
    _write(state / "authority_approval_constitution_effective.json", constitution)

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "production": True,
        "constitution_id": CONSTITUTION_ID,
        "canonical_flow_id": CANONICAL_FLOW_ID,
        "active_candidate_count": sum(1 for row in candidates if not row.get("terminal_stop")),
        "approval_flow_submission_count": len(submitted),
        "existing_review_flow_packet_count": len(review_packets),
        "cross_pr_shared_candidate_count": shared_count,
        "excluded_noncanonical_packet_count": excluded_noncanonical,
        "cooldown_skipped_count": skipped_cooldown,
        "terminal_skipped_count": terminal_skipped,
        "peer_share_task_count": len(peer_tasks),
        "approvers": list(APPROVERS),
        "collaborators": list(COLLABORATORS),
        "resubmit_cooldown_seconds": RESUBMIT_COOLDOWN_SECONDS,
        "approval_submission_is_goal": True,
        "META_X_SENJU_primary_review_is_first": True,
        "secondary_owner_or_standing_evidence_rank": 3,
        "secondary_evidence_may_raise_review_priority": False,
        "unlisted_approval_flows_excluded": True,
        "fresh_evidence_resubmits_immediately": True,
        "unchanged_candidate_periodic_resubmission": True,
        "writes_existing_review_surface": True,
        "writes_shared_opportunity_queue": True,
        "authority_effect": "none",
        "authority_activated": False,
        "terminal_stop_bypass": False,
    }
    _write(state / "negotiation_submission_accelerator_result.json", result)
    return result
