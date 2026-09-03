"""Bidirectional shared evidence bus for negotiation and authorized-host promotion.

The bus connects Shared Discovery / Boundary Opportunity research, META/X/SENJU rights
requests, and Root Authority negotiation. Every shared opportunity carries the binding
council-first approval constitution so all participating AI/PR loops use the same review
order. The bus never activates Authority or performs external writes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from engine.authority_approval_constitution import (
    ALL_PARTICIPANTS,
    CANONICAL_FLOW_ID,
    CONSTITUTION_ID,
    EXPIRED_CASE_RECONSIDERATION_SECONDS,
    PRIMARY_APPROVERS,
    SECONDARY_VALIDATION_RANK,
    UNPROCESSED_CASE_EXPIRY_SECONDS,
    constitutional_metadata,
)

SCHEMA = "the-world-authority-collaboration-bus/v2"
QUEUE_SCHEMA = "the-world-authority-opportunity-queue/v1"

RIGHTS_FILES = (
    "rights_request_ledger.json",
    "rights_request_federation.json",
    "owner_scope_negotiation_signals.json",
    "owner_scope_negotiation_result.json",
    "owner_scope_negotiation_ballots.json",
    "owner_scope_expansion_evidence.json",
    "owner_contact_ceiling_effective.json",
    "council_operational_governance_result.json",
    "council_operational_policy.json",
)
BOUNDARY_FILES = (
    "boundary_opportunities.json",
    "boundary_opportunity_cycle_result.json",
    "shared_discovery_opportunity_bridge.json",
    "boundary_evolution_checkpoint.json",
)
ROOT_FILES = (
    "root_authority_negotiation_state.json",
    "root_authority_negotiation_campaign.json",
    "root_authority_negotiation_run.json",
    "owner_root_authority_review_packets.json",
)
PROMOTION_FILES = (
    "promotion_packets.json",
    "execution_ready.json",
    "last_promotion_cycle.json",
)
PROMOTION_PRIORITY = {
    "READY_FOR_STANDING_AUTHORIZATION": 98,
    "NEGOTIATION_PENDING": 94,
    "METHOD_SCOPE_MISMATCH": 92,
    "RUNTIME_APPLY_PENDING": 90,
    "AUTHORIZED_EXECUTION_READY": 88,
}


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host(value: Any) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    if not raw:
        return ""
    if "://" in raw:
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return ""
        if parsed.username or parsed.password:
            return ""
        raw = (parsed.hostname or "").lower().rstrip(".")
    if not raw or any(ch in raw for ch in "/?#@*"):
        return ""
    return raw


def _priority(value: Any, default: int = 70) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = default
    return max(1, min(score, 100))


def _confidence(value: Any, default: float = 0.7) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    if score > 1:
        score /= 10 if score <= 10 else 100
    return max(0.0, min(score, 1.0))


def _methods(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return sorted({str(v).strip().upper() for v in values if str(v).strip().upper() in VALID_METHODS})


def _copy_existing(source_dir: Path | None, bus_dir: Path, names: Iterable[str]) -> list[str]:
    copied: list[str] = []
    if source_dir is None:
        return copied
    for name in names:
        src = source_dir / name
        if not src.is_file():
            continue
        dst = bus_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            same = src.resolve() == dst.resolve()
        except OSError:
            same = False
        if not same:
            shutil.copyfile(src, dst)
        copied.append(name)
    return copied


def _existing_opportunities(bus_dir: Path) -> list[dict[str, Any]]:
    doc = _load(bus_dir / "authority_opportunity_queue.json", {})
    rows = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _constitutional_fields() -> dict[str, Any]:
    return {
        "authority_approval_constitution_id": CONSTITUTION_ID,
        "canonical_approval_flow_id": CANONICAL_FLOW_ID,
        "primary_approvers": list(PRIMARY_APPROVERS),
        "primary_approval_stage": "executive_council_primary_review",
        "executive_approval_promotes_to": "parliamentary_review_queue",
        "unprocessed_case_expiry_seconds": UNPROCESSED_CASE_EXPIRY_SECONDS,
        "expired_case_reconsideration_seconds": EXPIRED_CASE_RECONSIDERATION_SECONDS,
        "time_elapsed_is_approval": False,
        "secondary_owner_or_standing_evidence_rank": SECONDARY_VALIDATION_RANK,
        "secondary_evidence_may_raise_review_priority": False,
        "unlisted_approval_flows_excluded": True,
    }


def _from_rights(rights_dir: Path | None) -> list[dict[str, Any]]:
    if rights_dir is None:
        return []
    doc = _load(rights_dir / "rights_request_ledger.json", {})
    rows = doc.get("requests", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status", ""))
        if not status.startswith(("requesting_", "owner_review_", "council_review_")):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        terminal = bool(row.get("hard_deny") is True or row.get("revoked") is True)
        out.append({
            "host": host,
            "reason": str(row.get("reason") or "META/X/SENJU request broader authority review")[:400],
            "priority": _priority(row.get("priority"), 82),
            "confidence": min(0.99, 0.72 + min(int(row.get("seen_count", 1) or 1), 9) * 0.02),
            "requested_methods": _methods(row.get("requested_methods", [])),
            "source": "rights_request_federation",
            "source_ref": row.get("request_id"),
            "status": status,
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": False,
            "revoked": False,
            **_constitutional_fields(),
        })
    return out


def _from_boundary(boundary_dir: Path | None) -> list[dict[str, Any]]:
    if boundary_dir is None:
        return []
    doc = _load(boundary_dir / "boundary_opportunities.json", {})
    rows = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("disposition", "proposal_only")) != "proposal_only":
            continue
        if not isinstance(row.get("proposal_signal"), Mapping):
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
        host = _host(row.get("host") or evidence.get("host"))
        if not host:
            continue
        out.append({
            "host": host,
            "reason": str(
                evidence.get("reason")
                or row.get("capability_unlocked")
                or "Boundary research produced a proposal-safe council review candidate"
            )[:400],
            "priority": _priority(row.get("priority_score"), 76),
            "confidence": _confidence(row.get("confidence_score"), 0.75),
            "requested_methods": _methods(row.get("requested_methods", [])),
            "source": "boundary_opportunity_research",
            "source_ref": row.get("opportunity_id"),
            "status": "boundary_proposal",
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": False,
            "revoked": False,
            **_constitutional_fields(),
        })
    return out


def _from_root(root_dir: Path | None) -> list[dict[str, Any]]:
    if root_dir is None:
        return []
    doc = _load(root_dir / "root_authority_negotiation_state.json", {})
    rows = doc.get("candidates", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        terminal = bool(row.get("terminal_stop"))
        readiness = _priority(row.get("readiness_score"), 78)
        reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
        out.append({
            "host": host,
            "reason": str(reasons[0] if reasons else row.get("status") or "Root negotiation candidate")[:400],
            "priority": max(78, readiness),
            "confidence": _confidence(readiness, 0.78),
            "requested_methods": ["GET", "HEAD", "OPTIONS"],
            "source": "root_authority_negotiation",
            "source_ref": row.get("candidate_id"),
            "source_refs": list(row.get("source_refs", [])) if isinstance(row.get("source_refs"), list) else [],
            "status": str(row.get("status") or "persistent_root_authority_negotiation"),
            "proof_type": row.get("owner_proof_type"),
            "proof_ref": row.get("owner_proof_ref"),
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": terminal,
            "revoked": terminal and str(row.get("status")) == "revoked",
        })
    return out


def _from_promotion(promotion_dir: Path | None) -> list[dict[str, Any]]:
    if promotion_dir is None:
        return []
    doc = _load(promotion_dir / "promotion_packets.json", {})
    rows = doc.get("packets", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        status = str(row.get("status") or "promotion_feedback")
        terminal = bool(status == "BLOCKED_TERMINAL" or row.get("hard_deny") or row.get("revoked"))
        out.append({
            "host": host,
            "reason": str(row.get("next_action") or "Promotion Corps requests more negotiation evidence")[:400],
            "priority": PROMOTION_PRIORITY.get(status, 84),
            "confidence": _confidence(row.get("average_yes_confidence"), 0.84),
            "requested_methods": _methods(row.get("requested_methods", [])),
            "source": "authorized_host_promotion_corps",
            "source_ref": row.get("proposal_id"),
            "status": status,
            "proof_type": row.get("proof_type"),
            "proof_ref": row.get("proof_ref"),
            "standing_authorization_match": bool(row.get("standing_authorization_match")),
            "council_unanimous": bool(row.get("council_unanimous")),
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": terminal,
            "revoked": bool(row.get("revoked")),
        })
    return out


def _from_execution_ready(promotion_dir: Path | None) -> list[dict[str, Any]]:
    if promotion_dir is None:
        return []
    doc = _load(promotion_dir / "execution_ready.json", {})
    rows = doc.get("records", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        out.append({
            "host": host,
            "reason": str(row.get("next_action") or "execution-ready existing standing authority")[:400],
            "priority": PROMOTION_PRIORITY["AUTHORIZED_EXECUTION_READY"],
            "confidence": _confidence(row.get("average_yes_confidence"), 0.95),
            "requested_methods": _methods(row.get("covered_methods", [])),
            "source": "authorized_host_promotion_corps",
            "source_ref": row.get("proposal_id"),
            "status": "AUTHORIZED_EXECUTION_READY",
            "proof_type": row.get("proof_type"),
            "proof_ref": row.get("proof_ref"),
            "standing_authorization_match": True,
            "council_unanimous": bool(row.get("council_unanimous")),
            "execution_ready": True,
            "proposal_only": False,
            "authority_effect": "existing_standing_authorization_lease",
            "hard_deny": False,
            "revoked": False,
        })
    return out


def _from_owner_decisions(state_dir: Path | None) -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    doc = _load(state_dir / "owner_scope_negotiation_result.json", {})
    rows = doc.get("decisions", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        out.append({
            "host": host,
            "reason": str(row.get("reason") or "Owner Scope negotiation decision")[:400],
            "priority": 90 if row.get("applied") else 84,
            "confidence": _confidence(row.get("average_yes_confidence"), 0.8),
            "source": "owner_scope_negotiation_result",
            "source_ref": row.get("proposal_id"),
            "status": str(row.get("status") or "owner_scope_decision"),
            "proof_type": row.get("proof_type"),
            "proof_ref": row.get("proof_ref"),
            "council_unanimous": int(row.get("yes_votes", 0) or 0) >= 3,
            "hard_deny": str(row.get("status")) == "terminal_stop",
            "revoked": bool(row.get("revoked")),
        })
    return out


def _from_owner_evidence(state_dir: Path | None) -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    doc = _load(state_dir / "owner_scope_expansion_evidence.json", {})
    rows = doc.get("evidence", []) if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host"))
        if not host:
            continue
        out.append({
            "host": host,
            "reason": "verified Owner-scope evidence" if row.get("verified") else "unverified Owner-scope evidence",
            "priority": 96 if row.get("verified") else 75,
            "confidence": 0.98 if row.get("verified") else 0.55,
            "source": "owner_scope_expansion_evidence",
            "source_ref": row.get("proof_ref"),
            "status": "verified_owner_evidence" if row.get("verified") else "unverified_owner_evidence",
            "proof_type": row.get("proof_type"),
            "proof_ref": row.get("proof_ref"),
            "hard_deny": bool(row.get("hard_deny")),
            "revoked": bool(row.get("revoked")),
        })
    return out


def _merge(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    terminal_hosts: set[str] = set()
    for raw in rows:
        host = _host(raw.get("host") or raw.get("target") or raw.get("url"))
        if not host:
            continue
        if raw.get("hard_deny") is True or raw.get("revoked") is True:
            merged.pop(host, None)
            continue
        if host in terminal_hosts:
            continue
        current = merged.get(host)
        source = str(raw.get("source") or "existing_authority_opportunity")
        source_ref = str(raw.get("source_ref") or raw.get("request_id") or raw.get("opportunity_id") or "")
        if current is None:
            current = {
                "host": host,
                "reason": str(raw.get("reason") or "Authority opportunity")[:400],
                "priority": _priority(raw.get("priority") or raw.get("priority_score"), 70),
                "confidence": _confidence(raw.get("confidence") or raw.get("confidence_score"), 0.7),
                "requested_methods": _methods(raw.get("requested_methods", [])),
                "sources": [],
                "source_refs": [],
                "statuses": [],
                "proof_types": [],
                "proof_refs": [],
                "proposal_only": True,
                "authority_effect": "none",
                "hard_deny": False,
                "revoked": False,
                **_constitutional_fields(),
            }
            merged[host] = current
        current.update(_constitutional_fields())
        current["priority"] = max(int(current["priority"]), _priority(raw.get("priority") or raw.get("priority_score"), 70))
        current["confidence"] = max(float(current["confidence"]), _confidence(raw.get("confidence") or raw.get("confidence_score"), 0.7))
        if source and source not in current["sources"]:
            current["sources"].append(source)
        refs = [source_ref]
        if isinstance(raw.get("source_refs"), list):
            refs.extend(str(v) for v in raw.get("source_refs", []) if str(v))
        for ref in refs:
            if ref and ref not in current["source_refs"]:
                current["source_refs"].append(ref)
        status = str(raw.get("status") or "")
        if status and status not in current["statuses"]:
            current["statuses"].append(status)
        proof_type = str(raw.get("proof_type") or "")
        if proof_type and proof_type not in current["proof_types"]:
            current["proof_types"].append(proof_type)
        proof_ref = str(raw.get("proof_ref") or "")
        if proof_ref and proof_ref not in current["proof_refs"]:
            current["proof_refs"].append(proof_ref)
        current["requested_methods"] = sorted(set(current["requested_methods"]) | set(_methods(raw.get("requested_methods", []))))
    return sorted(merged.values(), key=lambda row: (-int(row["priority"]), row["host"]))


def _build_evidence_bundle(rows: Iterable[Mapping[str, Any]], *, generated_at: int) -> dict[str, Any]:
    by_host: dict[str, dict[str, Any]] = {}
    for raw in rows:
        host = _host(raw.get("host") or raw.get("target") or raw.get("url"))
        if not host:
            continue
        item = by_host.setdefault(host, {
            "host": host,
            "priority": 1,
            "confidence": 0.0,
            "requested_methods": set(),
            "sources": set(),
            "source_refs": set(),
            "reasons": [],
            "statuses": set(),
            "proof_types": set(),
            "proof_refs": set(),
            "standing_authorization_match": False,
            "council_unanimous": False,
            "execution_ready": False,
            "terminal_stop": False,
        })
        item["priority"] = max(int(item["priority"]), _priority(raw.get("priority"), 70))
        item["confidence"] = max(float(item["confidence"]), _confidence(raw.get("confidence"), 0.7))
        item["requested_methods"].update(_methods(raw.get("requested_methods", [])))
        source = str(raw.get("source") or "")
        if source:
            item["sources"].add(source)
        if isinstance(raw.get("sources"), list):
            item["sources"].update(str(v) for v in raw.get("sources", []) if str(v))
        source_ref = str(raw.get("source_ref") or "")
        if source_ref:
            item["source_refs"].add(source_ref)
        if isinstance(raw.get("source_refs"), list):
            item["source_refs"].update(str(v) for v in raw.get("source_refs", []) if str(v))
        reason = str(raw.get("reason") or raw.get("next_action") or "")[:400]
        if reason and reason not in item["reasons"]:
            item["reasons"].append(reason)
        status = str(raw.get("status") or "")
        if status:
            item["statuses"].add(status)
        if isinstance(raw.get("statuses"), list):
            item["statuses"].update(str(v) for v in raw.get("statuses", []) if str(v))
        proof_type = str(raw.get("proof_type") or "")
        if proof_type:
            item["proof_types"].add(proof_type)
        if isinstance(raw.get("proof_types"), list):
            item["proof_types"].update(str(v) for v in raw.get("proof_types", []) if str(v))
        proof_ref = str(raw.get("proof_ref") or "")
        if proof_ref:
            item["proof_refs"].add(proof_ref)
        if isinstance(raw.get("proof_refs"), list):
            item["proof_refs"].update(str(v) for v in raw.get("proof_refs", []) if str(v))
        item["standing_authorization_match"] = bool(item["standing_authorization_match"] or raw.get("standing_authorization_match"))
        item["council_unanimous"] = bool(item["council_unanimous"] or raw.get("council_unanimous"))
        item["execution_ready"] = bool(item["execution_ready"] or raw.get("execution_ready") or status == "AUTHORIZED_EXECUTION_READY")
        item["terminal_stop"] = bool(
            item["terminal_stop"]
            or raw.get("hard_deny")
            or raw.get("revoked")
            or status in {"BLOCKED_TERMINAL", "terminal_stop"}
        )

    normalized: dict[str, dict[str, Any]] = {}
    for host, item in sorted(by_host.items()):
        normalized[host] = {
            "host": host,
            "priority": int(item["priority"]),
            "confidence": round(float(item["confidence"]), 4),
            "requested_methods": sorted(item["requested_methods"]),
            "sources": sorted(item["sources"]),
            "source_refs": sorted(item["source_refs"])[:64],
            "reasons": item["reasons"][:16],
            "statuses": sorted(item["statuses"]),
            "proof_types": sorted(item["proof_types"]),
            "proof_refs": sorted(item["proof_refs"])[:32],
            "standing_authorization_match": bool(item["standing_authorization_match"]),
            "council_unanimous": bool(item["council_unanimous"]),
            "execution_ready": bool(item["execution_ready"]),
            "terminal_stop": bool(item["terminal_stop"]),
        }
    return {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": generated_at,
        "host_count": len(normalized),
        "hosts": normalized,
    }


def _task_kind(row: Mapping[str, Any]) -> str | None:
    if row.get("terminal_stop"):
        return None
    statuses = set(str(v) for v in row.get("statuses", []) if str(v))
    if row.get("execution_ready"):
        return "execution_handoff"
    if "READY_FOR_STANDING_AUTHORIZATION" in statuses:
        return "standing_authorization_evidence"
    if "METHOD_SCOPE_MISMATCH" in statuses:
        return "method_scope_reconciliation"
    if "RUNTIME_APPLY_PENDING" in statuses:
        return "runtime_apply_followthrough"
    if "NEGOTIATION_PENDING" in statuses:
        return "council_evidence_alignment"
    return "evidence_fusion"


def _mission(actor: str, kind: str, host: str) -> str:
    common = {
        "standing_authorization_evidence": f"collect and cross-check exact-host authorization evidence for {host}; publish refs back to the shared bundle",
        "method_scope_reconciliation": f"reconcile the smallest requested method set for {host} with the already-authorized method ceiling",
        "runtime_apply_followthrough": f"verify why {host} has not reached runtime application and feed the precise blocker back into negotiation",
        "council_evidence_alignment": f"review the shared evidence for {host}, identify disagreement, and publish an independently reasoned ballot/evidence update",
        "evidence_fusion": f"fuse fresh evidence for {host}, remove duplicates, and publish independently checkable refs to the shared negotiation memory",
        "execution_handoff": f"verify the existing-standing-authority execution handoff for {host} and preserve the receipt for the next cycle",
    }
    suffix = {
        "META": " Prioritize state continuity and same-or-narrower lease readiness.",
        "X": " Independently challenge scope assumptions and method fit.",
        "SENJU": " Verify the handoff, decision consistency, and production evidence.",
        "PR-ARMY": " Correlate related PR and code evidence without changing authority.",
        "CHILD": " Gather non-secret public/authorized evidence and report concise refs.",
        "AI": " Synthesize contradictions and propose the next evidence-gathering step.",
    }
    return common[kind] + suffix.get(actor, "")


def _build_agent_inboxes(bundle: Mapping[str, Any], *, generated_at: int, max_items: int) -> dict[str, Any]:
    hosts = bundle.get("hosts", {}) if isinstance(bundle, Mapping) else {}
    rows = list(hosts.values()) if isinstance(hosts, Mapping) else []
    rows = [row for row in rows if isinstance(row, Mapping)]
    rows.sort(key=lambda row: (-int(row.get("priority", 0)), str(row.get("host", ""))))
    by_agent: dict[str, list[dict[str, Any]]] = {actor: [] for actor in AGENTS}
    for row in rows:
        kind = _task_kind(row)
        if kind is None:
            continue
        host = str(row.get("host"))
        for actor in AGENTS:
            if len(by_agent[actor]) >= max_items:
                continue
            by_agent[actor].append({
                "task_id": f"collaboration:{host}:{actor.lower()}:{kind}",
                "actor": actor,
                "host": host,
                "kind": kind,
                "priority": int(row.get("priority", 70)),
                "confidence": float(row.get("confidence", 0.7)),
                "mission": _mission(actor, kind, host),
                "requested_methods": list(row.get("requested_methods", [])),
                "sources": list(row.get("sources", [])),
                "source_refs": list(row.get("source_refs", []))[:16],
                "statuses": list(row.get("statuses", [])),
                "proof_types": list(row.get("proof_types", [])),
                "execution_ready": bool(row.get("execution_ready")),
                "shared_evidence_ref": f"negotiation_evidence_bundle.json#hosts.{host}",
                "authority_effect": "existing_standing_only" if row.get("execution_ready") else "none",
            })
    return {
        "schema": INBOX_SCHEMA,
        "generated_at": generated_at,
        "agents": list(AGENTS),
        "task_count": sum(len(v) for v in by_agent.values()),
        "inboxes": by_agent,
    }


def _coordination_protocol(generated_at: int) -> dict[str, Any]:
    return {
        "schema": COORDINATION_SCHEMA,
        "generated_at": generated_at,
        "actors": list(AGENTS),
        "rules": [
            "same_exact_host_uses_one_shared_evidence_bundle",
            "new_evidence_and_promotion_feedback_are_reingested_next_cycle",
            "terminal_deny_or_revocation_propagates_to_all_agents",
            "source_refs_are_preserved_across_root_owner_scope_and_promotion_loops",
            "execution_ready_means_existing_active_standing_authorization_only",
            "requested_methods_are_reconciled_same_or_narrower_before_execution_handoff",
        ],
        "capabilities": {
            "all_agents": [
                "read_shared_negotiation_evidence",
                "publish_evidence_refs",
                "consume_promotion_feedback",
                "reuse_cross_loop_source_refs",
                "propose_precise_next_actions",
            ],
            "META": ["cast_owner_scope_ballot", "prepare_same_or_narrower_existing_lease"],
            "X": ["cast_owner_scope_ballot", "prepare_same_or_narrower_existing_lease"],
            "SENJU": ["cast_owner_scope_ballot", "verify_execution_handoff"],
            "PR-ARMY": ["cross_pr_evidence_fusion"],
            "CHILD": ["authorized_or_public_evidence_collection"],
            "AI": ["contradiction_detection", "evidence_gap_planning"],
        },
        "authority_effect": "none",
        "new_unrelated_authority_mint": False,
        "credential_access": False,
    }


def build_authority_collaboration_bus(
    bus_dir: str | Path,
    *,
    rights_state_dir: str | Path | None = None,
    boundary_state_dir: str | Path | None = None,
    root_state_dir: str | Path | None = None,
    promotion_state_dir: str | Path | None = None,
    max_inbox_items: int = 128,
    now: int | None = None,
) -> dict[str, Any]:
    bus = Path(bus_dir)
    bus.mkdir(parents=True, exist_ok=True)
    rights = Path(rights_state_dir) if rights_state_dir else bus
    boundary = Path(boundary_state_dir) if boundary_state_dir else bus
    root = Path(root_state_dir) if root_state_dir else bus
    promotion = Path(promotion_state_dir) if promotion_state_dir else bus
    copied = (
        _copy_existing(rights, bus, RIGHTS_FILES)
        + _copy_existing(boundary, bus, BOUNDARY_FILES)
        + _copy_existing(root, bus, ROOT_FILES)
        + _copy_existing(promotion, bus, PROMOTION_FILES)
    )

    existing = _existing_opportunities(bus)
    rights_rows = _from_rights(rights)
    signal_rows = _from_signals(rights)
    boundary_rows = _from_boundary(boundary)
    root_rows = _from_root(root)
    promotion_rows = _from_promotion(promotion)
    opportunities = _merge([*existing, *boundary_rows, *rights_rows, *signal_rows, *root_rows, *promotion_rows])
    generated_at = int(time.time()) if now is None else int(now)
    constitution = constitutional_metadata()

    queue = {
        "schema": QUEUE_SCHEMA,
        "generated_at": generated_at,
        "producer": "authority_collaboration_bus",
        "proposal_only": True,
        "authority_activated": False,
        "external_side_effects": False,
        "constitution": constitution,
        "opportunities": opportunities,
        "opportunity_count": len(opportunities),
    }
    _write(bus / "authority_opportunity_queue.json", queue)
    _write(bus / "authority_approval_constitution_effective.json", constitution)

    evidence_rows: list[Mapping[str, Any]] = [
        *opportunities,
        *rights_rows,
        *signal_rows,
        *boundary_rows,
        *root_rows,
        *promotion_rows,
        *_from_execution_ready(promotion),
        *_from_owner_decisions(rights),
        *_from_owner_evidence(rights),
    ]
    evidence = _build_evidence_bundle(evidence_rows, generated_at=generated_at)
    _write(bus / "negotiation_evidence_bundle.json", evidence)

    inboxes = _build_agent_inboxes(
        evidence,
        generated_at=generated_at,
        max_items=max(1, min(int(max_inbox_items), 512)),
    )
    _write(bus / "negotiation_agent_inboxes.json", inboxes)
    for actor, tasks in inboxes["inboxes"].items():
        _write(bus / "agent-inbox" / f"{actor.lower()}.json", {
            "schema": "the-world-negotiation-agent-inbox/v2",
            "generated_at": generated_at,
            "actor": actor,
            "tasks": tasks,
            "task_count": len(tasks),
        })

    protocol = _coordination_protocol(generated_at)
    _write(bus / "negotiation_coordination_protocol.json", protocol)

    summary = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "closed_loop": True,
        "bidirectional_exchange": True,
        "promotion_feedback_reingested": True,
        "shared_runtime": str(bus),
        "constitution": constitution,
        "producers": ["Shared Discovery/Boundary Research", "META/X/SENJU Rights Federation", "Root Negotiation"],
        "consumers": list(ALL_PARTICIPANTS) + ["Root Authority Negotiation"],
        "copied_files": sorted(set(copied)),
        "rights_candidate_count": len(rights_rows),
        "signal_candidate_count": len(signal_rows),
        "boundary_candidate_count": len(boundary_rows),
        "root_candidate_count": len(root_rows),
        "promotion_candidate_count": len(promotion_rows),
        "opportunity_count": len(opportunities),
        "META_X_SENJU_primary_review_is_first": True,
        "executive_approval_promotes_to_parliamentary_review": True,
        "unprocessed_case_expiry_seconds": UNPROCESSED_CASE_EXPIRY_SECONDS,
        "expired_case_reconsideration_seconds": EXPIRED_CASE_RECONSIDERATION_SECONDS,
        "time_elapsed_is_approval": False,
        "secondary_owner_or_standing_evidence_rank": SECONDARY_VALIDATION_RANK,
        "unlisted_approval_flows_excluded": True,
        "authority_effect": "none",
        "authority_activated": False,
        "external_side_effects": False,
        "credential_access": False,
        "hard_deny_override": False,
    }
    _write(bus / "authority_collaboration_bus.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-dir", required=True)
    parser.add_argument("--rights-state-dir")
    parser.add_argument("--boundary-state-dir")
    parser.add_argument("--root-state-dir")
    parser.add_argument("--promotion-state-dir")
    parser.add_argument("--max-inbox-items", type=int, default=128)
    parser.add_argument("--json-out")
    args = parser.parse_args()
    result = build_authority_collaboration_bus(
        args.bus_dir,
        rights_state_dir=args.rights_state_dir,
        boundary_state_dir=args.boundary_state_dir,
        root_state_dir=args.root_state_dir,
        promotion_state_dir=args.promotion_state_dir,
        max_inbox_items=args.max_inbox_items,
    )
    if args.json_out:
        _write(Path(args.json_out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
