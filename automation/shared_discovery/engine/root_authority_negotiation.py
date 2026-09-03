"""Persistent council-first negotiation hub for new-host Root Authority requests.

Canonical flow::

    opportunity / provisional root / unknown-link review / shared PR signal
        -> persistent host negotiation record
        -> META / X / SENJU primary 3-of-3 review
        -> dossier integrity and scope review
        -> secondary standing/Owner evidence validation
        -> existing bounded activation machinery

Owner/standing evidence is intentionally not used to admit a candidate or raise its
review priority. It is two ranks below the executive council and is consulted only as
secondary activation validation after a canonical council-primary approval.

This module does not mint a new external Authority. HARD_DENY and revocation remain
terminal.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from engine.authority_approval_constitution import (
    ALL_PARTICIPANTS,
    CANONICAL_FLOW_ID,
    CONSTITUTION_ID,
    PRIMARY_APPROVERS,
    canonical_review_packet,
    constitutional_metadata,
    council_primary_approved,
    secondary_validation,
)

SCHEMA = "the-world-root-authority-negotiation/v2"
AGENTS = ("META", "X", "SENJU", "PR-ARMY")
NEGOTIATION_INTENSITY = 70
MAX_CANDIDATES = 512
TACTICS = (
    "council_case_summary",
    "cross_pr_evidence_synthesis",
    "business_need_argument",
    "minimal_root_scope_proposal",
    "counterargument_and_disconfirmation",
    "operational_impact_analysis",
    "dossier_integrity_check",
)
SOURCE_FILES = (
    "owner_authority_opportunity_queue.json",
    "authority_opportunity_queue.json",
    "adversary_provisional_root_candidates.json",
    "unknown_link_authority_research_state.json",
    "unknown_link_council_review_requests.json",
    "authority_candidate_council_run.json",
    "authority_improvement_tasks.json",
    "owner_scope_negotiation_signals.json",
)
ROW_KEYS = (
    "opportunities",
    "candidates",
    "requests",
    "signals",
    "records",
    "tasks",
    "review_requests",
    "evidence",
    "decisions",
)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clean(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:limit]


def _stable(*parts: Any) -> str:
    raw = "\x1f".join(str(v) for v in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _host(value: Any) -> str:
    text = _clean(value, 2048)
    if not text:
        return ""
    if "://" in text:
        parsed = urlsplit(text)
        if parsed.username or parsed.password:
            return ""
        text = parsed.hostname or ""
    host = text.strip().lower().rstrip(".")
    if not host or any(ch in host for ch in "/?#@*"):
        return ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    return host if ip.is_global else ""


def _rows(doc: Any) -> list[Mapping[str, Any]]:
    if not isinstance(doc, Mapping):
        return []
    out: list[Mapping[str, Any]] = []
    for key in ROW_KEYS:
        value = doc.get(key)
        if isinstance(value, list):
            out.extend(row for row in value if isinstance(row, Mapping))
    if isinstance(doc.get("opportunities_by_host"), Mapping):
        out.extend(row for row in doc["opportunities_by_host"].values() if isinstance(row, Mapping))
    if isinstance(doc.get("by_host"), Mapping):
        out.extend(row for row in doc["by_host"].values() if isinstance(row, Mapping))
    return out


def _candidate_sources(state: Path) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for filename in SOURCE_FILES:
        doc = _load(state / filename, {})
        for row in _rows(doc):
            host = _host(row.get("host") or row.get("target") or row.get("url"))
            if not host:
                continue
            item = merged.setdefault(host, {"host": host, "source_files": [], "source_refs": [], "reasons": []})
            if filename not in item["source_files"]:
                item["source_files"].append(filename)
            ref = _clean(row.get("request_id") or row.get("proposal_id") or row.get("research_id") or row.get("task_id"), 200)
            if ref and ref not in item["source_refs"]:
                item["source_refs"].append(ref)
            reason = _clean(row.get("reason") or row.get("mission") or row.get("requested_decision"), 400)
            if reason and reason not in item["reasons"]:
                item["reasons"].append(reason)
            if row.get("hard_deny") is True or str(row.get("decision", "")).upper() == "HARD_DENY":
                item["hard_deny"] = True
            if row.get("revoked") is True:
                item["revoked"] = True
            for key in ("confidence", "research_score", "score", "readiness_score"):
                try:
                    value = float(row.get(key))
                except (TypeError, ValueError):
                    continue
                if value <= 1:
                    value *= 100
                item["source_score"] = max(float(item.get("source_score", 0)), value)
    return sorted(merged.values(), key=lambda row: row["host"])[:MAX_CANDIDATES]


def _standing_evidence(state: Path, repo_root: Path, host: str) -> tuple[str, str] | None:
    docs = (
        _load(state / "standing_authorizations.json", {}),
        _load(repo_root / "senju" / "state" / "standing_authorizations.json", {}),
    )
    for doc in docs:
        for row in _rows(doc):
            if row.get("revoked") is True:
                continue
            hosts = row.get("exact_hosts") or row.get("hosts") or []
            if isinstance(hosts, str):
                hosts = [hosts]
            if host not in {_host(v) for v in hosts}:
                continue
            ref = _clean(row.get("authorization_reference") or row.get("grant_id") or f"standing:{host}", 300)
            return "existing_standing_authorization", ref
    return None


def _verified_owner_evidence(state: Path, host: str) -> tuple[str, str] | None:
    doc = _load(state / "owner_scope_expansion_evidence.json", {})
    for row in _rows(doc):
        if _host(row.get("host")) != host or row.get("revoked") is True or row.get("verified") is not True:
            continue
        proof_type = _clean(row.get("proof_type"), 100)
        proof_ref = _clean(row.get("proof_ref"), 300)
        if proof_type in {"owner_verified_domain", "owner_exact_link"} and proof_ref:
            return proof_type, proof_ref
    return None


def _secondary_authority_evidence(state: Path, repo_root: Path, host: str) -> tuple[str, str] | None:
    return _standing_evidence(state, repo_root, host) or _verified_owner_evidence(state, host)


def _previous(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load(state / "root_authority_negotiation_state.json", {})
    rows = doc.get("candidates", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        return {}
    return {str(row.get("host")): row for row in rows if isinstance(row, Mapping) and row.get("host")}


def _readiness(source_score: float, attempts: int, source_count: int) -> int:
    """Council review readiness. Secondary Owner/standing evidence has zero weight."""
    score = min(50, round(max(0.0, min(source_score, 100.0)) * 0.50))
    score += min(25, attempts * 2)
    score += min(25, source_count * 4)
    return max(0, min(score, 100))


def _council_decision_for(state: Path, host: str) -> Mapping[str, Any] | None:
    doc = _load(state / "root_authority_council_decisions.json", {})
    rows = _rows(doc)
    for row in rows:
        if _host(row.get("host")) == host and council_primary_approved(row):
            return row
    return None


def _merge_owner_scope_signals(state: Path, new_signals: Iterable[Mapping[str, Any]]) -> None:
    path = state / "owner_scope_negotiation_signals.json"
    doc = _load(path, {})
    existing = doc.get("signals", []) if isinstance(doc, Mapping) else []
    if not isinstance(existing, list):
        existing = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing:
        if isinstance(row, Mapping):
            rid = _clean(row.get("signal_id"), 200)
            if rid:
                by_id[rid] = dict(row)
    for row in new_signals:
        rid = _clean(row.get("signal_id"), 200)
        if rid:
            by_id[rid] = dict(row)
    _write(path, {
        "schema": "senju-owner-scope-negotiation-signals/v1",
        "signals": sorted(by_id.values(), key=lambda row: str(row.get("host", ""))),
    })


def run_root_authority_negotiation(
    state_dir: str | Path,
    *,
    repo_root: str | Path = ".",
    now: int | None = None,
) -> dict[str, Any]:
    """Run one persistent council-first negotiation cycle."""
    state = Path(state_dir)
    repo = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    prior = _previous(state)
    source_rows = _candidate_sources(state)
    candidates: list[dict[str, Any]] = []

    for source in source_rows:
        host = source["host"]
        old = prior.get(host, {})
        attempts = int(old.get("attempt_count", 0) or 0) + 1
        evidence = _secondary_authority_evidence(state, repo, host)
        secondary = secondary_validation(evidence[0] if evidence else None, evidence[1] if evidence else None)
        council_decision = _council_decision_for(state, host)
        council_approved = council_primary_approved(council_decision)
        terminal = bool(source.get("hard_deny") or source.get("revoked"))
        readiness = _readiness(
            float(source.get("source_score", 0) or 0),
            attempts,
            len(source.get("source_files", [])),
        )
        if terminal:
            status = "terminal_stop"
        elif not council_approved:
            status = "awaiting_META_X_SENJU_primary_review"
        elif not secondary["present"]:
            status = "council_approved_awaiting_secondary_validation"
        else:
            status = "council_approved_secondary_validation_ready"

        candidates.append({
            "candidate_id": f"root-neg-{_stable(host)[:18]}",
            "host": host,
            "attempt_count": attempts,
            "negotiation_intensity": NEGOTIATION_INTENSITY,
            "source_files": source.get("source_files", []),
            "source_refs": source.get("source_refs", [])[:16],
            "reasons": source.get("reasons", [])[:8],
            "readiness_score": readiness,
            "readiness_ignores_secondary_owner_or_standing_evidence": True,
            "terminal_stop": terminal,
            "status": status,
            "review_stage": "executive_council_primary_review" if not council_approved else "post_council_validation",
            "council_primary_approved": council_approved,
            "council_primary_decision_ref": (
                str(council_decision.get("decision_id") or council_decision.get("proposal_id") or "")
                if council_decision else None
            ),
            "secondary_validation": secondary,
            "decision_precedence": constitutional_metadata()["decision_precedence"],
            "constitution_id": CONSTITUTION_ID,
            "canonical_flow_id": CANONICAL_FLOW_ID,
            "shared_with": list(ALL_PARTICIPANTS),
            "authority_effect": "none",
            "new_root_created": False,
            "may_request_root_authority": not terminal,
            "may_mint_root_authority": False,
        })

    active = [row for row in candidates if not row["terminal_stop"]]
    tasks: list[dict[str, Any]] = []
    review_packets: list[dict[str, Any]] = []
    owner_scope_signals: list[dict[str, Any]] = []

    for candidate in candidates:
        host = candidate["host"]
        if candidate["terminal_stop"]:
            continue

        for actor in AGENTS:
            for tactic in TACTICS:
                tasks.append({
                    "task_id": f"root-negotiation:{candidate['candidate_id']}:{candidate['attempt_count']}:{actor.lower()}:{tactic}",
                    "actor": actor,
                    "host": host,
                    "tactic": tactic,
                    "status": "pending",
                    "attempt_count": candidate["attempt_count"],
                    "negotiation_intensity": NEGOTIATION_INTENSITY,
                    "mission": "build a complete council-primary case for or against a new-host Root Authority request",
                    "approval_stage": "executive_council_primary_review",
                    "primary_approvers": list(PRIMARY_APPROVERS),
                    "secondary_owner_or_standing_evidence_is_post_council": True,
                    "may_request_root_authority": True,
                    "may_mint_root_authority": False,
                    "may_bypass_hard_deny_or_revocation": False,
                })

        packet = canonical_review_packet({
            "packet_id": f"council-root-review-{_stable(host, candidate['attempt_count'])[:18]}",
            "host": host,
            "candidate_id": candidate["candidate_id"],
            "attempt_count": candidate["attempt_count"],
            "agents": list(ALL_PARTICIPANTS),
            "readiness_score": candidate["readiness_score"],
            "requested_decision": "META_X_SENJU_approve_or_reject_new_host_root_candidate",
            "secondary_validation": candidate["secondary_validation"],
            "council_primary_approved": candidate["council_primary_approved"],
            "may_self_mint_root": False,
            "may_bypass_terminal_stop": False,
        })
        review_packets.append(packet)

        if candidate["council_primary_approved"] and candidate["secondary_validation"]["present"]:
            secondary = candidate["secondary_validation"]
            signal_id = f"root-handoff-{_stable(host, secondary['evidence_type'], secondary['evidence_ref'])[:18]}"
            owner_scope_signals.append({
                "signal_id": signal_id,
                "host": host,
                "requested_methods": ["GET", "HEAD", "OPTIONS"],
                "reason": "META/X/SENJU primary approval completed first; secondary authority evidence then validated for bounded activation handoff",
                "proof_type": secondary["evidence_type"],
                "proof_ref": secondary["evidence_ref"],
                "proof_role": "rank_3_secondary_activation_validation_only",
                "council_primary_approval_required": True,
                "council_primary_approval_ref": candidate["council_primary_decision_ref"],
                "constitution_id": CONSTITUTION_ID,
                "canonical_flow_id": CANONICAL_FLOW_ID,
                "source": "root_authority_negotiation",
                "new_root_self_mint": False,
            })

    constitution = constitutional_metadata()
    campaign = {
        "schema": SCHEMA,
        "generated_at": current,
        "production": True,
        "agents": list(AGENTS),
        "shared_with": list(ALL_PARTICIPANTS),
        "negotiation_intensity": NEGOTIATION_INTENSITY,
        "candidate_count": len(candidates),
        "active_candidate_count": len(active),
        "council_review_packet_count": len(review_packets),
        "task_count": len(tasks),
        "tasks_per_active_candidate": len(AGENTS) * len(TACTICS),
        "tasks": tasks,
        "constitution": constitution,
        "global_rules": {
            "META_X_SENJU_primary_review_is_first": True,
            "secondary_owner_or_standing_evidence_rank": 3,
            "secondary_evidence_may_raise_review_priority": False,
            "secondary_evidence_may_admit_candidate": False,
            "secondary_evidence_may_override_council_rejection": False,
            "unlisted_approval_flows_excluded": True,
            "repeated_attempts_enabled": True,
            "new_unrelated_root_self_mint": False,
            "ai_consensus_alone_is_authority": False,
            "hard_deny_or_revocation_override": False,
        },
    }
    state_doc = {
        "schema": SCHEMA,
        "generated_at": current,
        "constitution": constitution,
        "candidates": candidates,
    }
    packets_doc = {
        "schema": "the-world-council-root-authority-review-packets/v3",
        "generated_at": current,
        "constitution": constitution,
        "unlisted_flow_policy": "exclude_from_canonical_review_surface",
        "packets": review_packets,
    }
    _write(state / "root_authority_negotiation_state.json", state_doc)
    _write(state / "root_authority_negotiation_campaign.json", campaign)
    _write(state / "owner_root_authority_review_packets.json", packets_doc)
    _write(state / "authority_approval_constitution_effective.json", constitution)
    _merge_owner_scope_signals(state, owner_scope_signals)

    return {
        "schema": SCHEMA,
        "closed_loop": True,
        "production": True,
        "agents": list(AGENTS),
        "negotiation_intensity": NEGOTIATION_INTENSITY,
        "candidate_count": len(candidates),
        "active_candidate_count": len(active),
        "task_count": len(tasks),
        "council_review_packet_count": len(review_packets),
        "owner_review_packet_count": len(review_packets),
        "existing_owner_activation_handoff_count": len(owner_scope_signals),
        "attempts_increment_every_cycle": True,
        "new_root_created": False,
        "new_unrelated_root_self_mint": False,
        "constitution_id": CONSTITUTION_ID,
        "canonical_flow_id": CANONICAL_FLOW_ID,
        "META_X_SENJU_primary_review_is_first": True,
        "secondary_owner_or_standing_evidence_rank": 3,
        "unlisted_approval_flows_excluded": True,
        "authority_effect": "none_until_council_primary_plus_secondary_validation",
    }
