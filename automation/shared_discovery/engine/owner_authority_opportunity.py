"""Persistent opportunity explorer for unresolved owner-authority proposals.

The explorer gives autonomous agents room to keep looking for a legitimate authority
path without turning inference into authority by itself. It repeatedly re-checks the
same evidence sources used by production discovery authorization:

    inferred intent / similarity / history / discovered link
        -> OWNER_AUTHORITY_OPPORTUNITY
        -> persistent autonomous re-checks
        -> independent authority proof appears
        -> existing discovery authorization promotes the exact host
        -> bounded recursive delegation may activate

The opportunity queue never mints a new unrelated Owner root. Rotation and "curiosity"
slots affect search priority only; they never affect authorization outcomes.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import (
    _authorization_basis,
    _company_domains,
    _load_json,
    _normalize_host,
    _owner_supplied_exact_hosts,
    _reviewed_explicit_exact_hosts,
    _standing_authorized_exact_hosts,
    _trusted_roots,
)

OPPORTUNITY_SCHEMA = "meta-owner-authority-opportunity/v1"
MAX_OPPORTUNITIES = 512
AUTONOMOUS_AGENTS = ("META", "X", "SENJU", "CHILD", "AI")
SEARCH_STRATEGIES = (
    "recheck_trusted_root",
    "recheck_company_domain",
    "recheck_standing_authorization",
    "recheck_reviewed_explicit_grant",
    "recheck_owner_supplied_exact_link",
    "reassess_historical_similarity",
    "curiosity_reorder_only",
)


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


def _rows(state: Path, filename: str, key: str) -> list[Mapping[str, Any]]:
    doc = _load_json(state / filename, {})
    values = doc.get(key, []) if isinstance(doc, Mapping) else []
    if not isinstance(values, list):
        return []
    return [row for row in values if isinstance(row, Mapping)]


def _intent_by_key(state: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in _rows(state, "human_intent_decisions.json", "decisions"):
        host = _host(row.get("host"))
        url = str(row.get("url", "")).strip()
        if host and url:
            result[(host, url)] = row
    return result


def _candidate_rows(state: Path) -> list[Mapping[str, Any]]:
    return _rows(state, "discovery_candidates.json", "candidates")


def _live_grants(state: Path, *, now: int) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "discovery_authorized.json", {})
    hosts = doc.get("hosts", {}) if isinstance(doc, Mapping) else {}
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(hosts, Mapping):
        return result
    for raw_host, grant in hosts.items():
        if not isinstance(grant, Mapping):
            continue
        host = _host(raw_host)
        if host is None:
            continue
        if int(grant.get("expires_at", 0)) <= now:
            continue
        result[host] = grant
    return result


def _previous_by_id(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "owner_authority_opportunity_queue.json", {})
    rows = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("opportunity_id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }


def _strategy_for(opportunity_id: str, attempt_count: int) -> tuple[str, bool]:
    # Stable per-opportunity phase offset plus cycle rotation gives variety without
    # creating flaky authorization behavior.
    phase = int(hashlib.sha256(opportunity_id.encode("utf-8")).hexdigest()[:8], 16)
    index = (phase + max(0, int(attempt_count) - 1)) % len(SEARCH_STRATEGIES)
    strategy = SEARCH_STRATEGIES[index]
    return strategy, strategy == "curiosity_reorder_only"


def _proof_sources(state: Path, repo_root: Path, host: str) -> dict[str, Any]:
    trusted_roots = _trusted_roots(state)
    company_domains = _company_domains(state)
    standing_exact = _standing_authorized_exact_hosts(repo_root)
    reviewed_exact = _reviewed_explicit_exact_hosts(state)
    owner_supplied_exact = _owner_supplied_exact_hosts(state)
    basis = _authorization_basis(
        host,
        trusted_roots=trusted_roots,
        company_domains=company_domains,
        standing_exact_hosts=standing_exact,
        reviewed_exact_hosts=reviewed_exact,
        owner_supplied_exact_hosts=owner_supplied_exact,
    )
    return {
        "basis": list(basis) if basis is not None else None,
        "trusted_root_match": any(host == root or host.endswith("." + root) for root in trusted_roots),
        "company_domain_match": any(host == root or host.endswith("." + root) for root in company_domains),
        "standing_exact_or_descendant": (
            host in standing_exact or any(host.endswith("." + exact) for exact in standing_exact)
        ),
        "reviewed_explicit_exact": host in reviewed_exact,
        "owner_supplied_exact_or_descendant": (
            host in owner_supplied_exact
            or any(host.endswith("." + exact) for exact in owner_supplied_exact)
        ),
    }


def _evidence_signals(intent: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    reasons = [str(item) for item in intent.get("reasons", [])]
    return {
        "intent_confidence": float(intent.get("confidence", 0.0) or 0.0),
        "likely_owner_intent": bool(intent.get("likely_owner_intent", False)),
        "similarity_signal": any(reason.startswith("prior_similarity:") for reason in reasons),
        "historical_approval_signal": "prior_explicit_approval_exists" in reasons,
        "owner_context_signal": "owner_context" in reasons,
        "discovered_or_supplied_link_signal": (
            "owner_supplied_matching_link" in reasons or bool(candidate.get("url"))
        ),
        "intent_reasons": reasons,
        "candidate_decision": candidate.get("decision"),
        "candidate_reason": candidate.get("reason"),
    }


def run_owner_authority_opportunity_loop(
    state_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Persist and autonomously re-check unresolved authority opportunities.

    A candidate becomes ``authority_found`` only when production's normal independent
    evidence model can already prove an authorization basis or a live discovery grant
    already exists. Inference alone can keep an opportunity hot, never activate it.
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    repository = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    now = _now()
    intents = _intent_by_key(state)
    grants = _live_grants(state, now=now)
    previous = _previous_by_id(state)
    opportunities: list[dict[str, Any]] = []

    for candidate in _candidate_rows(state):
        host = _host(candidate.get("host"))
        url = str(candidate.get("url", "")).strip()
        if host is None or not url:
            continue
        intent = intents.get((host, url), {})
        confidence = float(intent.get("confidence", 0.0) or 0.0)
        likely = bool(intent.get("likely_owner_intent", False))
        if not likely and confidence < 0.55:
            continue

        opportunity_id = _stable_id("owner-authority-opportunity", host, url)
        old = previous.get(opportunity_id, {})
        attempt_count = int(old.get("attempt_count", 0)) + 1
        first_seen_at = int(old.get("first_seen_at", now))
        strategy, curiosity_slot = _strategy_for(opportunity_id, attempt_count)
        proof = _proof_sources(state, repository, host)
        grant = grants.get(host)
        proof_found = proof.get("basis") is not None
        authority_found = grant is not None or proof_found
        credential_scope = str(grant.get("credential_scope", "none")).strip().lower() if grant else "none"
        delegation_ready = bool(grant is not None and credential_scope == "none")

        opportunities.append(
            {
                "opportunity_id": opportunity_id,
                "host": host,
                "url": url,
                "first_seen_at": first_seen_at,
                "last_checked_at": now,
                "attempt_count": attempt_count,
                "status": "authority_found" if authority_found else "searching",
                "current_strategy": strategy,
                "search_strategies": list(SEARCH_STRATEGIES),
                "autonomous_agents": list(AUTONOMOUS_AGENTS),
                "autonomous_recheck": True,
                "persistent_until_resolved": True,
                "signals": _evidence_signals(intent, candidate),
                "independent_authority_proof": proof,
                "live_authorization_reference": (
                    grant.get("authorization_reference") if grant is not None else None
                ),
                "recursive_delegation_ready": delegation_ready,
                "activation_condition": "existing_independent_authority_proof_or_live_grant",
                "may_mint_new_owner_root_from_inference": False,
                "credential_inheritance": False,
                "curiosity_slot": {
                    "active": curiosity_slot,
                    "effect": "search_order_only_never_authorization",
                },
            }
        )

    opportunities.sort(
        key=lambda row: (
            row["status"] != "authority_found",
            -float(row["signals"].get("intent_confidence", 0.0)),
            -int(row["attempt_count"]),
            str(row["host"]),
        )
    )
    opportunities = opportunities[:MAX_OPPORTUNITIES]
    payload = {
        "schema": OPPORTUNITY_SCHEMA,
        "generated_at": now,
        "mode": "persistent_autonomous_authority_opportunity_search",
        "rule": "keep_searching_for_independent_authority_proof_without_minting_from_inference",
        "autonomous_agents": list(AUTONOMOUS_AGENTS),
        "new_owner_root_from_inference": False,
        "opportunities": opportunities,
    }
    destination = state / "owner_authority_opportunity_queue.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "opportunity_count": len(opportunities),
        "searching_count": sum(1 for row in opportunities if row["status"] == "searching"),
        "authority_found_count": sum(1 for row in opportunities if row["status"] == "authority_found"),
        "delegation_ready_count": sum(1 for row in opportunities if row["recursive_delegation_ready"]),
        "total_attempt_count": sum(int(row["attempt_count"]) for row in opportunities),
        "new_owner_root_from_inference": False,
        "credential_inheritance": False,
    }
