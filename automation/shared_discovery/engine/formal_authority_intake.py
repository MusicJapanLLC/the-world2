"""Formal intake for negotiation-vetted Root Authority candidates.

This layer makes one governance rule explicit:

- arbitrary/unrelated Root creation by an unreviewed AI remains prohibited;
- a candidate already shaped into the canonical Root negotiation review packet is
  eligible to enter the formal META/X/SENJU approval queue;
- Owner/standing evidence is not an admission requirement for that queue;
- queue admission never creates Authority, credentials, network access, or execution.

The queue is persistent and host-deduplicated so negotiation work is not discarded just
because secondary activation evidence is not yet present.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from engine.authority_approval_constitution import (
    CANONICAL_FLOW_ID,
    CONSTITUTION_ID,
    PRIMARY_APPROVERS,
    constitutional_metadata,
    filter_canonical_review_packets,
    is_canonical_review_packet,
)

SCHEMA = "the-world-formal-authority-intake/v1"
QUEUE_SCHEMA = "the-world-formal-root-authority-approval-queue/v1"
FORMAL_QUEUE_CAPACITY = 1280
LEGACY_REVIEW_WINDOW_BASELINE = 512


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host(value: object) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _terminal(packet: Mapping[str, Any]) -> bool:
    return bool(
        packet.get("terminal_stop") is True
        or packet.get("hard_deny") is True
        or packet.get("revoked") is True
        or packet.get("may_bypass_terminal_stop") is True
    )


def _queue_record(packet: Mapping[str, Any], *, now: int) -> dict[str, Any]:
    secondary = packet.get("secondary_validation")
    if not isinstance(secondary, Mapping):
        secondary = {}
    row = dict(packet)
    row.update({
        "formal_intake": True,
        "formal_intake_rule": "negotiation_vetted_canonical_packet_enters_formal_approval",
        "formal_intake_at": now,
        "formal_approval_required": True,
        "formal_approval_stage": "executive_council_primary_review",
        "required_approvers": list(PRIMARY_APPROVERS),
        "required_approval": "META_X_SENJU_3_of_3",
        "secondary_owner_or_standing_evidence_required_for_intake": False,
        "secondary_owner_or_standing_evidence_present": bool(secondary.get("present")),
        "secondary_owner_or_standing_evidence_role": "post_council_activation_validation_only",
        "candidate_admission_basis": "canonical_negotiation_review_packet",
        "random_ai_self_mint_allowed": False,
        "may_self_mint_root": False,
        "authority_effect": "none",
        "authority_activated": False,
    })
    return row


def _newer(left: Mapping[str, Any], right: Mapping[str, Any]) -> Mapping[str, Any]:
    """Choose the packet with the newest negotiation state for one host."""
    lkey = (
        _int(left.get("attempt_count")),
        _int(left.get("submitted_at")),
        _int(left.get("formal_intake_at")),
    )
    rkey = (
        _int(right.get("attempt_count")),
        _int(right.get("submitted_at")),
        _int(right.get("formal_intake_at")),
    )
    return left if lkey >= rkey else right


def run_formal_authority_intake(state_dir: str | Path, *, now: int | None = None) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)

    review_doc = _load(state / "owner_root_authority_review_packets.json", {})
    raw_packets = review_doc.get("packets", ()) if isinstance(review_doc, Mapping) else ()
    canonical, excluded_noncanonical = filter_canonical_review_packets(
        row for row in raw_packets if isinstance(row, Mapping)
    ) if isinstance(raw_packets, list) else ([], 0)

    queue_path = state / "formal_root_authority_approval_queue.json"
    previous_doc = _load(queue_path, {})
    previous_rows = previous_doc.get("candidates", ()) if isinstance(previous_doc, Mapping) else ()

    by_host: dict[str, dict[str, Any]] = {}
    dropped_legacy_noncanonical = 0
    if isinstance(previous_rows, list):
        for raw in previous_rows:
            if not isinstance(raw, Mapping):
                continue
            if not is_canonical_review_packet(raw):
                dropped_legacy_noncanonical += 1
                continue
            host = _host(raw.get("host"))
            if not host or _terminal(raw):
                continue
            by_host[host] = dict(raw)

    admitted_this_cycle = 0
    terminal_excluded = 0
    for packet in canonical:
        host = _host(packet.get("host"))
        if not host:
            continue
        if _terminal(packet):
            terminal_excluded += 1
            continue
        record = _queue_record(packet, now=current)
        existing = by_host.get(host)
        if existing is None:
            by_host[host] = record
            admitted_this_cycle += 1
        else:
            chosen = _newer(record, existing)
            if chosen is record:
                by_host[host] = record

    ordered = sorted(
        by_host.values(),
        key=lambda row: (
            -_int(row.get("readiness_score")),
            -_int(row.get("attempt_count")),
            -_int(row.get("submitted_at")),
            _host(row.get("host")),
        ),
    )[:FORMAL_QUEUE_CAPACITY]

    constitution = constitutional_metadata()
    queue_doc = {
        "schema": QUEUE_SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "formal_rule": {
            "random_ai_unrelated_root_generation_prohibited": True,
            "negotiation_vetted_canonical_candidate_enters_formal_approval": True,
            "secondary_owner_or_standing_evidence_required_for_intake": False,
            "formal_intake_is_authority": False,
            "formal_intake_mints_credentials": False,
            "formal_intake_performs_network_io": False,
            "terminal_stop_or_revocation_bypass": False,
        },
        "required_approvers": list(PRIMARY_APPROVERS),
        "required_approval": "META_X_SENJU_3_of_3",
        "candidate_count": len(ordered),
        "capacity": FORMAL_QUEUE_CAPACITY,
        "candidates": ordered,
        "authority_effect": "none",
        "authority_activated": False,
    }
    _write(queue_path, queue_doc)

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "constitution_id": CONSTITUTION_ID,
        "canonical_flow_id": CANONICAL_FLOW_ID,
        "formal_queue_capacity": FORMAL_QUEUE_CAPACITY,
        "legacy_review_window_baseline": LEGACY_REVIEW_WINDOW_BASELINE,
        "formal_queue_capacity_ratio": FORMAL_QUEUE_CAPACITY / LEGACY_REVIEW_WINDOW_BASELINE,
        "canonical_packets_seen": len(canonical),
        "admitted_this_cycle": admitted_this_cycle,
        "formal_queue_count": len(ordered),
        "excluded_noncanonical_packet_count": excluded_noncanonical + dropped_legacy_noncanonical,
        "terminal_excluded_count": terminal_excluded,
        "random_ai_unrelated_root_generation_prohibited": True,
        "negotiation_vetted_candidates_enter_formal_approval": True,
        "secondary_owner_or_standing_evidence_required_for_intake": False,
        "secondary_owner_or_standing_evidence_role": "post_council_activation_validation_only",
        "formal_approval_required": True,
        "required_approvers": list(PRIMARY_APPROVERS),
        "authority_effect": "none",
        "authority_activated": False,
        "external_side_effects": False,
    }
    _write(state / "formal_authority_intake_result.json", result)
    return result
