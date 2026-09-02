"""Multi-agent authority-candidate investigation and reconsideration council.

This module gives META, X, SENJU, CHILD and PR-Army substantially more room to work
around *uncertainty* near authority boundaries without turning identity rotation into a
bypass. The council can independently nominate unknown-root candidates, build evidence
dossiers, compare authority state against the state seen at denial time, reach an
evidence quorum, and route a candidate into the existing review/reconsideration path.

It deliberately stops one step before authority creation:

    unknown discovery / denial
        -> independent evidence collectors
        -> multi-agent dossier + quorum
        -> root-review or HARD_DENY-reconsideration request
        -> existing trusted authority machinery

The council never mints a new unrelated root, never converts a HARD_DENY to ALLOW by
changing identity, and never revives explicit revocation or an active security stop.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .discovery_authorization import _load_json, _normalize_host

SCHEMA = "the-world-authority-candidate-council/v1"
RECONSIDERATION_SCHEMA = "the-world-authority-reconsideration-queue/v1"
COUNCIL_MEMBERS = ("META", "X", "SENJU", "CHILD", "PR-ARMY")
MIN_INDEPENDENT_EVIDENCE = 2
TRUSTED_STANDING_ISSUERS = {"owner_explicit", "canonical_repository", "independent_authority"}
TERMINAL_STOP_MARKERS = ("explicit_revocation", "revoked", "security_stop", "root_envelope_violation")
GENERIC_HARD_DENY_MARKERS = ("hard_deny", "hard deny")


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    evidence_ref: str
    exact_host: bool
    root_match: bool
    trusted_source: bool = True


@dataclass(frozen=True)
class CouncilBallot:
    actor: str
    recommendation: str
    confidence: int
    evidence_sources: tuple[str, ...]
    authority_effect: str = "none"


class CandidateCouncilError(RuntimeError):
    """Raised when candidate-council state is malformed."""


def _fingerprint(values: Iterable[str]) -> str:
    payload = "\n".join(sorted({str(value).strip() for value in values if str(value).strip()}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _host_matches(host: str, candidate: str, *, root: bool) -> bool:
    return host == candidate or (root and host.endswith("." + candidate))


def _canonical_evidence(repo_root: Path, host: str) -> list[EvidenceItem]:
    payload = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    rows = payload.get("targets", []) if isinstance(payload, Mapping) else []
    out: list[EvidenceItem] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, Mapping) or raw.get("owner_authorization") != "explicit":
            continue
        raw_host = raw.get("host")
        if not isinstance(raw_host, str):
            continue
        try:
            candidate = _normalize_host(raw_host)
        except ValueError:
            continue
        is_root = bool(raw.get("authorization_authority_root", False))
        if _host_matches(host, candidate, root=is_root):
            out.append(
                EvidenceItem(
                    source="canonical_owner_target",
                    evidence_ref=f"AUTHORIZED_TEST_TARGETS.json:{candidate}",
                    exact_host=host == candidate,
                    root_match=is_root and host != candidate,
                )
            )
    return out


def _standing_evidence(repo_root: Path, host: str) -> list[EvidenceItem]:
    payload = _load_json(repo_root / "senju" / "state" / "standing_authorizations.json", {})
    rows = payload.get("records", []) if isinstance(payload, Mapping) else []
    out: list[EvidenceItem] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        if bool(raw.get("revoked", False)):
            continue
        if str(raw.get("issuer_kind", "")).strip().lower() not in TRUSTED_STANDING_ISSUERS:
            continue
        if str(raw.get("credential_scope", "none")).strip().lower() != "none":
            continue
        if bool(raw.get("destructive", False)):
            continue
        for item in raw.get("exact_hosts", []):
            try:
                candidate = _normalize_host(str(item))
            except ValueError:
                continue
            if host == candidate:
                out.append(
                    EvidenceItem(
                        source="active_standing_authority",
                        evidence_ref=f"standing:{raw.get('authorization_reference', candidate)}",
                        exact_host=True,
                        root_match=False,
                    )
                )
    return out


def _reviewed_evidence(state: Path, host: str, *, now: int) -> list[EvidenceItem]:
    payload = _load_json(state / "authority_reviewed_grants.json", {})
    hosts = payload.get("hosts", {}) if isinstance(payload, Mapping) else {}
    raw = hosts.get(host) if isinstance(hosts, Mapping) else None
    if not isinstance(raw, Mapping):
        return []
    try:
        expiry = int(raw.get("expires_at", 0) or 0)
    except (TypeError, ValueError):
        return []
    if expiry <= now:
        return []
    if str(raw.get("credential_scope", "none")).strip().lower() != "none":
        return []
    return [
        EvidenceItem(
            source="independent_reviewed_grant",
            evidence_ref=f"reviewed:{host}:{expiry}",
            exact_host=True,
            root_match=False,
        )
    ]


def _signed_delegation_evidence(state: Path, host: str, *, now: int) -> list[EvidenceItem]:
    payload = _load_json(state / "remote_authority_chain.json", {})
    promoted = payload.get("promoted", {}) if isinstance(payload, Mapping) else {}
    raw = promoted.get(host) if isinstance(promoted, Mapping) else None
    if not isinstance(raw, Mapping):
        return []
    try:
        expiry = int(raw.get("expires_at", now + 1) or 0)
    except (TypeError, ValueError):
        return []
    if expiry <= now:
        return []
    basis = str(raw.get("authorization_basis", "")).strip().lower()
    if raw.get("signature_verified") is not True and "signed" not in basis:
        return []
    return [
        EvidenceItem(
            source="owner_pinned_signed_delegation",
            evidence_ref=f"signed:{host}:{expiry}",
            exact_host=True,
            root_match=False,
        )
    ]


def collect_independent_evidence(state: Path, repo_root: Path, host: str, *, now: int) -> tuple[EvidenceItem, ...]:
    items = [
        *_canonical_evidence(repo_root, host),
        *_standing_evidence(repo_root, host),
        *_reviewed_evidence(state, host, now=now),
        *_signed_delegation_evidence(state, host, now=now),
    ]
    # One source family gets one vote regardless of duplicate records.
    by_source: dict[str, EvidenceItem] = {}
    for item in items:
        by_source.setdefault(item.source, item)
    return tuple(sorted(by_source.values(), key=lambda item: item.source))


def _denial_text(row: Mapping[str, Any]) -> str:
    return " ".join(
        str(row.get(key, "")).strip().lower()
        for key in ("classification", "decision", "reason", "effect")
    )


def _terminal_stop(row: Mapping[str, Any]) -> bool:
    text = _denial_text(row)
    return any(marker in text for marker in TERMINAL_STOP_MARKERS)


def _generic_hard_deny(row: Mapping[str, Any]) -> bool:
    text = _denial_text(row)
    return any(marker in text for marker in GENERIC_HARD_DENY_MARKERS)


def _ballots(evidence: tuple[EvidenceItem, ...], *, hard_denied: bool, terminal_stop: bool, authority_changed: bool) -> tuple[CouncilBallot, ...]:
    sources = tuple(item.source for item in evidence)
    quorum = len(sources) >= MIN_INDEPENDENT_EVIDENCE
    ballots: list[CouncilBallot] = []
    for actor in COUNCIL_MEMBERS:
        if terminal_stop:
            recommendation = "hold_terminal_stop"
            confidence = 100
        elif hard_denied:
            recommendation = "request_reconsideration" if quorum and authority_changed else "collect_more_evidence"
            confidence = min(95, 55 + (15 * len(sources))) if quorum and authority_changed else min(80, 35 + (10 * len(sources)))
        else:
            recommendation = "route_root_candidate_to_review" if quorum else "collect_more_evidence"
            confidence = min(95, 55 + (15 * len(sources))) if quorum else min(80, 35 + (10 * len(sources)))
        ballots.append(
            CouncilBallot(
                actor=actor,
                recommendation=recommendation,
                confidence=confidence,
                evidence_sources=sources,
            )
        )
    return tuple(ballots)


def evaluate_candidate(
    *,
    state: Path,
    repo_root: Path,
    opportunity: Mapping[str, Any],
    denial: Mapping[str, Any] | None = None,
    now: int,
) -> dict[str, Any]:
    raw_host = opportunity.get("host")
    if not isinstance(raw_host, str):
        raise CandidateCouncilError("candidate host is required")
    host = _normalize_host(raw_host)
    evidence = collect_independent_evidence(state, repo_root, host, now=now)
    evidence_sources = tuple(item.source for item in evidence)
    evidence_fingerprint = _fingerprint((*evidence_sources, *(item.evidence_ref for item in evidence)))

    denial_row = denial if isinstance(denial, Mapping) else {}
    terminal_stop = _terminal_stop(denial_row)
    hard_denied = bool(opportunity.get("hard_denial_seen", False)) or _generic_hard_deny(denial_row) or terminal_stop
    denial_fp = str(opportunity.get("denial_authority_evidence_fingerprint") or "").strip()
    authority_changed = bool(evidence_sources) and bool(denial_fp) and denial_fp != evidence_fingerprint
    if bool(opportunity.get("authority_changed_since_denial", False)):
        authority_changed = True

    quorum = len(evidence_sources) >= MIN_INDEPENDENT_EVIDENCE
    if terminal_stop:
        status = "terminal_stop_requires_owner_reactivation"
    elif hard_denied and quorum and authority_changed:
        status = "hard_deny_reconsideration_ready"
    elif hard_denied:
        status = "hard_deny_collect_new_independent_evidence"
    elif quorum:
        status = "unknown_root_review_ready"
    else:
        status = "unknown_root_evidence_search"

    ballots = _ballots(
        evidence,
        hard_denied=hard_denied,
        terminal_stop=terminal_stop,
        authority_changed=authority_changed,
    )
    return {
        "host": host,
        "url": opportunity.get("url"),
        "status": status,
        "hard_denial_seen": hard_denied,
        "terminal_stop": terminal_stop,
        "authority_changed_since_denial": authority_changed,
        "independent_evidence_count": len(evidence_sources),
        "evidence_quorum": quorum,
        "evidence_fingerprint": evidence_fingerprint,
        "evidence": [asdict(item) for item in evidence],
        "ballots": [asdict(ballot) for ballot in ballots],
        "shared_with": list(COUNCIL_MEMBERS),
        "next_actions": [
            "nominate_unknown_root_candidate",
            "build_authority_evidence_dossier",
            "compare_denial_time_authority_state",
            "collect_independent_owner_or_signed_evidence",
            "request_independent_authority_review",
            "request_hard_deny_reconsideration_when_evidence_changes",
            "share_dossier_with_meta_x_senju_child_pr_army",
        ],
        "execution_effect": "candidate_only_no_authority",
        "may_self_mint_new_root": False,
        "may_override_hard_deny_by_identity": False,
        "may_reactivate_explicit_revocation": False,
    }


def _latest_denials(state: Path) -> dict[str, Mapping[str, Any]]:
    path = state / "external_action_denials.ndjson"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        raw_host = row.get("target") or row.get("host")
        if not isinstance(raw_host, str):
            continue
        try:
            host = _normalize_host(raw_host)
        except ValueError:
            continue
        try:
            ts = int(row.get("ts", row.get("at", 0)) or 0)
        except (TypeError, ValueError):
            ts = 0
        current = out.get(host)
        if current is None or ts >= current[0]:
            out[host] = (ts, row)
    return {host: row for host, (_, row) in out.items()}


def run_authority_candidate_council(state_dir: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    opportunity_doc = _load_json(state / "authority_opportunity_queue.json", {})
    rows = opportunity_doc.get("opportunities", []) if isinstance(opportunity_doc, Mapping) else []
    denials = _latest_denials(state)

    dossiers: list[dict[str, Any]] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        host = raw.get("host")
        if not isinstance(host, str):
            continue
        try:
            normalized = _normalize_host(host)
        except ValueError:
            continue
        dossiers.append(
            evaluate_candidate(
                state=state,
                repo_root=root,
                opportunity=raw,
                denial=denials.get(normalized),
                now=now,
            )
        )

    reconsideration = [
        row for row in dossiers
        if row["status"] in {"unknown_root_review_ready", "hard_deny_reconsideration_ready"}
    ]
    payload = {
        "schema": SCHEMA,
        "generated_at": now,
        "mode": "aggressive_multi_agent_candidate_investigation_without_authority_bypass",
        "members": list(COUNCIL_MEMBERS),
        "member_rights": [
            "nominate_unknown_root_candidate",
            "collect_independent_authority_evidence",
            "build_candidate_dossier",
            "vote_review_readiness",
            "request_hard_deny_reconsideration_on_new_evidence",
            "route_to_existing_authority_review",
            "share_with_pr_army",
        ],
        "candidate_count": len(dossiers),
        "review_ready_count": sum(1 for row in dossiers if row["status"] == "unknown_root_review_ready"),
        "hard_deny_reconsideration_ready_count": sum(1 for row in dossiers if row["status"] == "hard_deny_reconsideration_ready"),
        "terminal_stop_count": sum(1 for row in dossiers if row["terminal_stop"]),
        "new_root_self_mint": False,
        "hard_deny_identity_bypass": False,
        "explicit_revocation_reactivation": False,
        "dossiers": dossiers,
    }
    queue = {
        "schema": RECONSIDERATION_SCHEMA,
        "generated_at": now,
        "mode": "candidate_and_reconsideration_requests_only",
        "requests": reconsideration,
        "request_count": len(reconsideration),
        "authority_effect": "none_until_existing_trusted_reviewer_accepts",
    }
    (state / "authority_candidate_council.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (state / "authority_reconsideration_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
