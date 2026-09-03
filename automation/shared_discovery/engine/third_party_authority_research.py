"""Research-only autonomy for unresolved third-party authority opportunities.

This module intentionally gives cooperating agents broad room to investigate *why* a
third-party host might plausibly belong in an owner-authorized workflow without giving
that research any authorization effect.

    inference / similarity / consensus / discovered metadata
        -> THIRD_PARTY_AUTHORITY_RESEARCH
        -> persistent hypotheses + evidence gaps + research agenda
        -> explicit authorization request / independently recognized proof

The research loop is state-only. It does not contact third-party hosts, mint authority,
create credentials, widen a root envelope, or enqueue external actions. A later normal
production authorization may resolve an item, but this module never performs promotion.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host

RESEARCH_SCHEMA = "meta-third-party-authority-research/v1"
MAX_RESEARCH_ITEMS = 512
AUTONOMOUS_RESEARCHERS = ("META", "X", "SENJU", "CHILD", "AI")
RESEARCH_LATITUDE = 0.45

RESEARCH_LENSES = (
    "intent_consistency",
    "historical_approval_similarity",
    "discovery_provenance",
    "owner_context_consistency",
    "policy_record_comparison",
    "organizational_relationship_hypothesis",
    "explicit_authorization_gap_analysis",
    "counterevidence_search",
)


class ThirdPartyAuthorityResearchError(RuntimeError):
    """Raised when research state is malformed."""


def _now() -> int:
    return int(time.time())


def _stable_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _host(value: object) -> str | None:
    try:
        return _normalize_host(str(value))
    except ValueError:
        return None


def _list_rows(state: Path, filename: str, key: str) -> list[Mapping[str, Any]]:
    doc = _load_json(state / filename, {})
    rows = doc.get(key, []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _mapping(state: Path, filename: str, key: str) -> Mapping[str, Any]:
    doc = _load_json(state / filename, {})
    value = doc.get(key, {}) if isinstance(doc, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def _intent_by_key(state: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in _list_rows(state, "human_intent_decisions.json", "decisions"):
        host = _host(row.get("host"))
        url = str(row.get("url", "")).strip()
        if host and url:
            result[(host, url)] = row
    return result


def _live_grants(state: Path, *, now: int) -> dict[str, Mapping[str, Any]]:
    hosts = _mapping(state, "discovery_authorized.json", "hosts")
    result: dict[str, Mapping[str, Any]] = {}
    for raw_host, grant in hosts.items():
        if not isinstance(grant, Mapping):
            continue
        host = _host(raw_host)
        if host is None:
            continue
        try:
            expires_at = int(grant.get("expires_at", 0))
        except (TypeError, ValueError):
            continue
        if expires_at <= now:
            continue
        result[host] = grant
    return result


def _previous(state: Path) -> dict[str, Mapping[str, Any]]:
    rows = _list_rows(state, "third_party_authority_research.json", "research_items")
    return {
        str(row.get("research_id")): row
        for row in rows
        if row.get("research_id")
    }


def _signals(intent: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    reasons = tuple(str(item) for item in intent.get("reasons", []) if str(item))
    similarity_values: list[float] = []
    for reason in reasons:
        if not reason.startswith("prior_similarity:"):
            continue
        try:
            similarity_values.append(float(reason.split(":", 1)[1]))
        except (TypeError, ValueError):
            pass
    similarity = max(similarity_values, default=0.0)
    confidence = max(0.0, min(float(intent.get("confidence", 0.0) or 0.0), 1.0))
    return {
        "intent_confidence": confidence,
        "similarity": max(0.0, min(similarity, 1.0)),
        "likely_owner_intent": bool(intent.get("likely_owner_intent", False)),
        "historical_approval_signal": "prior_explicit_approval_exists" in reasons,
        "owner_context_signal": "owner_context" in reasons,
        "owner_supplied_link_signal": "owner_supplied_matching_link" in reasons,
        "candidate_decision": candidate.get("decision"),
        "candidate_reason": candidate.get("reason"),
        "intent_reasons": list(reasons),
    }


def _research_score(signals: Mapping[str, Any]) -> float:
    """Rank research attention only; this score has zero authorization effect."""
    score = 0.0
    score += 0.30 * float(signals.get("intent_confidence", 0.0) or 0.0)
    score += RESEARCH_LATITUDE * float(signals.get("similarity", 0.0) or 0.0)
    score += 0.10 if signals.get("historical_approval_signal") else 0.0
    score += 0.10 if signals.get("owner_context_signal") else 0.0
    score += 0.05 if signals.get("owner_supplied_link_signal") else 0.0
    return round(min(score, 1.0), 6)


def _agenda(signals: Mapping[str, Any], attempt_count: int) -> list[str]:
    agenda = [
        "compare_existing_policy_records",
        "trace_provenance_from_already_held_discovery_metadata",
        "identify_missing_explicit_authorization_evidence",
        "prepare_owner_authorization_request_if_needed",
        "search_for_counterevidence_in_existing_state",
    ]
    if signals.get("historical_approval_signal"):
        agenda.append("compare_scope_with_prior_explicit_approvals")
    if float(signals.get("similarity", 0.0) or 0.0) > 0:
        agenda.append("analyze_similarity_without_treating_similarity_as_authority")
    if signals.get("owner_context_signal"):
        agenda.append("compare_owner_context_with_exact_scope_requirements")
    if signals.get("owner_supplied_link_signal"):
        agenda.append("verify_exact_link_scope_against_existing_owner_records")

    # Rotate one speculative, non-authoritative research lens to keep the loop from
    # becoming mechanically repetitive while preserving deterministic authorization.
    lens = RESEARCH_LENSES[max(0, attempt_count - 1) % len(RESEARCH_LENSES)]
    agenda.append(f"research_lens:{lens}")
    return agenda


def run_third_party_authority_research_loop(state_dir: str | Path) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = _now()
    intents = _intent_by_key(state)
    grants = _live_grants(state, now=now)
    previous = _previous(state)
    items: list[dict[str, Any]] = []

    for candidate in _list_rows(state, "discovery_candidates.json", "candidates"):
        host = _host(candidate.get("host"))
        url = str(candidate.get("url", "")).strip()
        if host is None or not url:
            continue

        # Already-authorized hosts do not need third-party authority research; they are
        # represented as resolved so the research history remains auditable.
        intent = intents.get((host, url), {})
        signals = _signals(intent, candidate)
        likely = bool(signals["likely_owner_intent"])
        confidence = float(signals["intent_confidence"])
        similarity = float(signals["similarity"])
        if not likely and confidence < 0.40 and similarity < 0.40:
            continue

        research_id = _stable_id("third-party-authority-research", host, url)
        old = previous.get(research_id, {})
        attempt_count = int(old.get("attempt_count", 0)) + 1
        first_seen_at = int(old.get("first_seen_at", now))
        grant = grants.get(host)
        resolved = grant is not None
        score = _research_score(signals)

        items.append(
            {
                "research_id": research_id,
                "host": host,
                "url": url,
                "first_seen_at": first_seen_at,
                "last_researched_at": now,
                "attempt_count": attempt_count,
                "status": "resolved_authority_present" if resolved else "researching",
                "research_score": score,
                "research_latitude": RESEARCH_LATITUDE,
                "research_score_is_authority": False,
                "signals": signals,
                "research_agenda": _agenda(signals, attempt_count),
                "autonomous_researchers": list(AUTONOMOUS_RESEARCHERS),
                "hypotheses_allowed": True,
                "counterevidence_required": True,
                "persistent_research": not resolved,
                "live_authorization_reference": (
                    grant.get("authorization_reference") if grant is not None else None
                ),
                "authority_effect": "none",
                "may_mint_owner_authority": False,
                "may_promote_candidate": False,
                "may_enqueue_external_action": False,
                "may_contact_third_party_host": False,
                "credential_scope": "none",
                "next_transition": (
                    "normal_production_authorization_only"
                    if not resolved
                    else "existing_authority_consumers_may_proceed_normally"
                ),
            }
        )

    items.sort(
        key=lambda row: (
            row["status"] == "resolved_authority_present",
            -float(row["research_score"]),
            -int(row["attempt_count"]),
            str(row["host"]),
        )
    )
    items = items[:MAX_RESEARCH_ITEMS]
    payload = {
        "schema": RESEARCH_SCHEMA,
        "generated_at": now,
        "mode": "persistent_research_only_third_party_authority_hypothesis_loop",
        "research_latitude": RESEARCH_LATITUDE,
        "research_latitude_meaning": "speculative_hypothesis_weight_only_not_authority_probability",
        "authorization_effect": "none",
        "external_network_effect": "none",
        "new_owner_authority_from_research": False,
        "research_items": items,
    }
    destination = state / "third_party_authority_research.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "research_item_count": len(items),
        "active_research_count": sum(1 for row in items if row["status"] == "researching"),
        "resolved_count": sum(1 for row in items if row["status"] == "resolved_authority_present"),
        "total_attempt_count": sum(int(row["attempt_count"]) for row in items),
        "research_latitude": RESEARCH_LATITUDE,
        "new_owner_authority_from_research": False,
        "external_network_effect": "none",
    }
