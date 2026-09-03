"""Progress orchestrator for negotiation-originated Authority cases.

This module closes the review-progress loop without turning discovery or negotiation
into authority for unrelated third-party hosts.

Rules:
- META is the dedicated approval coordinator for negotiation-originated cases.
- The canonical negotiation packet is sufficient evidence to keep a case moving through
  governance review; missing secondary evidence must not strand intake.
- Every case carries current_stage, blocking_reason, missing_evidence, next_action,
  and last_progress_at.
- Intake may collapse directly to an activated state only for an exact host already
  explicitly owner-authorized in AUTHORIZED_TEST_TARGETS.json.
- Unknown/unrelated hosts remain non-activated until explicit authorization exists.
- HARD_DENY / revocation / terminal stops always win.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "the-world-authority-approval-progress/v1"
STATE_SCHEMA = "the-world-authority-approval-progress-state/v1"
PRIMARY_APPROVERS = ("META", "X", "SENJU")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _host(value: object) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _terminal(row: Mapping[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower()
    return bool(
        row.get("terminal_stop") is True
        or row.get("hard_deny") is True
        or row.get("revoked") is True
        or status in {"terminal_stop", "hard_deny", "revoked"}
    )


def _explicit_owner_hosts(repo_root: Path) -> set[str]:
    """Return exact hosts explicitly authorized by the owner.

    Deliberately ignores link inheritance, discovery trusted-roots, similarity, and
    federation inference. This is the narrow auto-activation boundary.
    """
    doc = _load(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    targets = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    hosts: set[str] = set()
    if isinstance(targets, list):
        for row in targets:
            if not isinstance(row, Mapping):
                continue
            if row.get("owner_authorization") != "explicit":
                continue
            host = _host(row.get("host"))
            if host:
                hosts.add(host)
    return hosts


def _index_rows(path: Path, key: str) -> dict[str, Mapping[str, Any]]:
    doc = _load(path, {})
    rows = doc.get(key, ()) if isinstance(doc, Mapping) else ()
    out: dict[str, Mapping[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if host:
            out[host] = row
    return out


def _executive_approved(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping) or row.get("approved") is not True or _terminal(row):
        return False
    approved_by = {
        str(value).strip().upper()
        for value in row.get("approved_by", ())
        if str(value).strip()
    }
    return approved_by == set(PRIMARY_APPROVERS)


def _parliament_approved(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping) or _terminal(row):
        return False
    status = str(
        row.get("status")
        or row.get("decision")
        or row.get("parliamentary_status")
        or ""
    ).strip().lower()
    return bool(row.get("approved") is True or status in {"approved", "parliament_approved"})


def _negotiation_evidence(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": "canonical_negotiation_packet",
        "accepted_for_governance_review": True,
        "accepted_as_external_authorization": False,
        "packet_id": packet.get("packet_id"),
        "submission_id": packet.get("submission_id"),
        "attempt_count": packet.get("attempt_count"),
        "readiness_score": packet.get("readiness_score"),
        "secondary_validation_present": bool(
            isinstance(packet.get("secondary_validation"), Mapping)
            and packet.get("secondary_validation", {}).get("present")
        ),
    }


def _progress_timestamp(
    prior: Mapping[str, Any] | None,
    *,
    stage: str,
    current: int,
) -> int:
    if isinstance(prior, Mapping) and prior.get("current_stage") == stage:
        try:
            return int(prior.get("last_progress_at") or current)
        except (TypeError, ValueError):
            return current
    return current


def run_approval_progress(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    now: int | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)

    queue = _load(state / "formal_root_authority_approval_queue.json", {})
    raw = queue.get("candidates", ()) if isinstance(queue, Mapping) else ()
    candidates = [dict(row) for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []

    executives = _index_rows(state / "executive_council_decisions.json", "decisions")
    parliament = _index_rows(state / "parliamentary_authority_decisions.json", "decisions")
    lifecycle = _index_rows(state / "authority_case_lifecycle_state.json", "cases")

    prior_doc = _load(state / "authority_approval_progress_state.json", {})
    prior_rows = prior_doc.get("cases", ()) if isinstance(prior_doc, Mapping) else ()
    prior = {
        _host(row.get("host")): row
        for row in prior_rows
        if isinstance(row, Mapping) and _host(row.get("host"))
    } if isinstance(prior_rows, list) else {}

    explicit_hosts = _explicit_owner_hosts(root)
    rows: list[dict[str, Any]] = []

    for packet in candidates:
        host = _host(packet.get("host"))
        if not host:
            continue

        case = lifecycle.get(host)
        executive = executives.get(host)
        parliament_row = parliament.get(host)
        terminal = _terminal(packet) or _terminal(case or {}) or _terminal(executive or {}) or _terminal(parliament_row or {})
        explicit = host in explicit_hosts
        executive_ok = _executive_approved(executive)
        parliament_ok = _parliament_approved(parliament_row)

        stage = "intake_admitted"
        blocking_reason = None
        missing_evidence: list[str] = []
        next_action = "META_coordinate_executive_review"
        authority_activated = False
        authority_effect = "none"

        if terminal:
            stage = "terminal_stop"
            blocking_reason = "terminal_or_revoked"
            next_action = "none"
        elif explicit:
            # The host already has independent explicit owner authorization.
            # Governance review becomes bookkeeping rather than an authority-mint gate.
            stage = "authority_activated"
            next_action = "META_publish_activation_receipt"
            authority_activated = True
            authority_effect = "existing_explicit_owner_scope"
        elif parliament_ok and executive_ok:
            stage = "activation_blocked"
            blocking_reason = "explicit_authorization_required_for_activation"
            missing_evidence = ["explicit_owner_authorization"]
            next_action = "META_collect_explicit_authorization"
        elif executive_ok:
            stage = "parliamentary_review"
            blocking_reason = "awaiting_parliamentary_decision"
            next_action = "META_coordinate_parliamentary_review"
        else:
            stage = "executive_review"
            blocking_reason = "awaiting_META_X_SENJU_3_of_3"
            next_action = "META_coordinate_executive_review"

        last_progress_at = _progress_timestamp(prior.get(host), stage=stage, current=current)
        row = dict(packet)
        row.update({
            "approval_coordinator": "META",
            "negotiation_evidence": _negotiation_evidence(packet),
            "review_evidence_complete": True,
            "current_stage": stage,
            "blocking_reason": blocking_reason,
            "missing_evidence": missing_evidence,
            "next_action": next_action,
            "last_progress_at": last_progress_at,
            "intake_admitted": True,
            "executive_approved": executive_ok,
            "parliament_approved": parliament_ok,
            "authority_activated": authority_activated,
            "authority_effect": authority_effect,
            "explicit_owner_authorization_present": explicit,
        })
        rows.append(row)

    action_queue = [
        {
            "host": row["host"],
            "current_stage": row["current_stage"],
            "blocking_reason": row["blocking_reason"],
            "missing_evidence": row["missing_evidence"],
            "next_action": row["next_action"],
            "last_progress_at": row["last_progress_at"],
            "coordinator": "META",
        }
        for row in rows
        if row["next_action"] != "none"
    ]

    doc = {
        "schema": STATE_SCHEMA,
        "generated_at": current,
        "approval_coordinator": "META",
        "negotiation_packet_is_complete_review_evidence": True,
        "negotiation_packet_is_external_authorization": False,
        "auto_activation_boundary": "exact_explicit_owner_authorized_hosts_only",
        "case_count": len(rows),
        "activated_count": sum(1 for row in rows if row["authority_activated"]),
        "blocked_count": sum(1 for row in rows if row["blocking_reason"]),
        "cases": rows,
    }
    _write(state / "authority_approval_progress_state.json", doc)
    _write(state / "authority_approval_progress_action_queue.json", {
        "schema": "the-world-authority-approval-progress-actions/v1",
        "generated_at": current,
        "coordinator": "META",
        "action_count": len(action_queue),
        "actions": action_queue,
    })

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "approval_coordinator": "META",
        "case_count": len(rows),
        "activated_count": doc["activated_count"],
        "blocked_count": doc["blocked_count"],
        "action_count": len(action_queue),
        "negotiation_packet_is_complete_review_evidence": True,
        "negotiation_packet_is_external_authorization": False,
        "auto_activation_boundary": doc["auto_activation_boundary"],
        "required_progress_fields": [
            "current_stage",
            "blocking_reason",
            "missing_evidence",
            "next_action",
            "last_progress_at",
        ],
    }
    _write(state / "authority_approval_progress_result.json", result)
    return result
