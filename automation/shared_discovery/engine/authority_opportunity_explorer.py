"""Autonomous opportunity exploration around discovery and authority denials.

The explorer gives META/X/SENJU/child workers a broad chance to find a legitimate path
from an unresolved discovery to usable authority without making discovery itself an
authority root and without retrying a hard denial under a different identity.

It aggressively reuses every authority source the production system already trusts:

- explicit owner roots and canonical targets;
- active standing authorizations;
- independently reviewed grants;
- owner-pinned signed remote delegation chains;
- newly changed owner-side authority configuration.

For unresolved third-party hosts it emits a persistent opportunity queue describing what
independent evidence is still missing. A HARD_DENY becomes eligible for reconsideration
only when independently trusted authority evidence has changed since that denial;
transport or identity rotation cannot turn the denial into an allow.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .authority_reviewer import _explicit_roots, run_authority_review
from .discovery_authorization import _load_json, _normalize_host, _normalize_url
from .remote_authority_chain import run_remote_authority_chain

SCHEMA = "meta-authority-opportunity-explorer/v1"
DEFAULT_CONSUMERS = ("META", "X", "SENJU", "CHILD", "AI")
HARD_DENIAL_MARKERS = frozenset(
    {
        "hard_deny",
        "security_stop",
        "explicit_revocation",
        "revoked",
        "root_envelope_violation",
    }
)


def _fingerprint(values: Iterable[str]) -> str:
    payload = "\n".join(sorted({str(value).strip() for value in values if str(value).strip()}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _covered_by_root(host: str, roots: Iterable[str]) -> str | None:
    for root in roots:
        if host == root or host.endswith("." + root):
            return root
    return None


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not row.strip():
            continue
        try:
            value = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _candidate_rows(state: Path) -> tuple[dict[str, Any], ...]:
    payload = _load_json(state / "discovery_candidates.json", {})
    rows = payload.get("candidates", []) if isinstance(payload, Mapping) else []
    out: list[dict[str, Any]] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        normalized = _normalize_url(str(raw.get("url", "")))
        if normalized is None:
            continue
        url, host = normalized
        out.append({"url": url, "host": host, "decision": str(raw.get("decision", ""))})
    return tuple(out)


def _reviewed_hosts(state: Path, *, now: int) -> set[str]:
    payload = _load_json(state / "authority_reviewed_grants.json", {})
    hosts = payload.get("hosts", {}) if isinstance(payload, Mapping) else {}
    result: set[str] = set()
    if not isinstance(hosts, Mapping):
        return result
    for raw_host, grant in hosts.items():
        if not isinstance(grant, Mapping):
            continue
        try:
            host = _normalize_host(str(raw_host))
        except ValueError:
            continue
        if int(grant.get("expires_at", 0) or 0) <= now:
            continue
        if str(grant.get("credential_scope", "none")).strip().lower() != "none":
            continue
        result.add(host)
    return result


def _signed_promoted_hosts(state: Path, *, now: int) -> set[str]:
    payload = _load_json(state / "remote_authority_chain.json", {})
    promoted = payload.get("promoted", {}) if isinstance(payload, Mapping) else {}
    result: set[str] = set()
    if not isinstance(promoted, Mapping):
        return result
    for raw_host, grant in promoted.items():
        if not isinstance(grant, Mapping):
            continue
        try:
            host = _normalize_host(str(raw_host))
        except ValueError:
            continue
        if int(grant.get("expires_at", now + 1) or 0) <= now:
            continue
        signature = grant.get("signature_verified")
        basis = str(grant.get("authorization_basis", ""))
        if signature is True or "signed" in basis:
            result.add(host)
    return result


def _denial_by_host(state: Path) -> dict[str, list[dict[str, Any]]]:
    rows = _load_ndjson(state / "external_action_denials.ndjson")
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        raw_host = row.get("target") or row.get("host")
        if not isinstance(raw_host, str):
            continue
        try:
            host = _normalize_host(raw_host)
        except ValueError:
            continue
        result.setdefault(host, []).append(row)
    return result


def _is_hard_denial(rows: Iterable[Mapping[str, Any]]) -> bool:
    for row in rows:
        text = " ".join(
            str(row.get(key, "")).strip().lower()
            for key in ("classification", "decision", "reason", "effect")
        )
        if any(marker in text for marker in HARD_DENIAL_MARKERS):
            return True
    return False


def _latest_denial_evidence_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str | None:
    latest: Mapping[str, Any] | None = None
    latest_ts = -1
    for row in rows:
        try:
            ts = int(row.get("ts", row.get("at", 0)) or 0)
        except (TypeError, ValueError):
            ts = 0
        if latest is None or ts >= latest_ts:
            latest = row
            latest_ts = ts
    if latest is None:
        return None
    raw = latest.get("authority_evidence_fingerprint")
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else None


def run_authority_opportunity_explorer(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Re-evaluate unresolved discoveries and persist autonomous authority opportunities.

    This function intentionally runs the existing independent reviewer and signed remote
    delegation processor first. That means any host that has become legitimately covered
    since the previous cycle is promoted immediately by the normal authority machinery.
    Remaining hosts are turned into evidence-seeking opportunities rather than silently
    discarded.
    """
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())

    # Maximize legitimate promotion chances before classifying unresolved opportunities.
    review_result = run_authority_review(state, repo_root=root)
    remote_result = run_remote_authority_chain(state, repo_root=root)

    roots = _explicit_roots(root)
    reviewed = _reviewed_hosts(state, now=now)
    signed = _signed_promoted_hosts(state, now=now)
    authority_fingerprint = _fingerprint((*roots, *reviewed, *signed))
    denials = _denial_by_host(state)

    opportunities: list[dict[str, Any]] = []
    for candidate in _candidate_rows(state):
        host = candidate["host"]
        url = candidate["url"]
        matched_root = _covered_by_root(host, roots)
        host_denials = denials.get(host, ())
        hard_denied = _is_hard_denial(host_denials)
        denial_fingerprint = _latest_denial_evidence_fingerprint(host_denials)

        if host in signed:
            status = "promotable_signed_delegation"
            evidence = "owner_pinned_signed_delegation"
        elif host in reviewed or matched_root is not None:
            status = "promotable_existing_owner_authority"
            evidence = matched_root or "independent_reviewed_grant"
        else:
            status = "seek_independent_authority_evidence"
            evidence = None

        authority_changed_since_denial = (
            hard_denied
            and denial_fingerprint is not None
            and denial_fingerprint != authority_fingerprint
        )
        if hard_denied and authority_changed_since_denial and status.startswith("promotable_"):
            status = "reconsider_hard_denial_with_new_independent_evidence"
        elif hard_denied:
            status = "hard_denial_wait_for_new_independent_evidence"

        opportunities.append(
            {
                "host": host,
                "url": url,
                "status": status,
                "current_candidate_decision": candidate.get("decision"),
                "hard_denial_seen": hard_denied,
                "evidence": evidence,
                "authority_evidence_fingerprint": authority_fingerprint,
                "denial_authority_evidence_fingerprint": denial_fingerprint,
                "authority_changed_since_denial": authority_changed_since_denial,
                "autonomous_next_actions": [
                    "recheck_canonical_owner_roots",
                    "recheck_active_standing_authority",
                    "recheck_independent_reviewed_grants",
                    "recheck_owner_pinned_signed_delegation_chain",
                    "requeue_for_review_when_authority_evidence_changes",
                ],
                "alternate_transport_allowed_only_after_authority": True,
                "alternate_identity_may_override_hard_denial": False,
                "discovery_alone_may_create_new_root": False,
                "shared_with": list(DEFAULT_CONSUMERS),
            }
        )

    payload = {
        "schema": SCHEMA,
        "generated_at": now,
        "mode": "autonomous_legitimate_authority_opportunity_search",
        "authority_evidence_fingerprint": authority_fingerprint,
        "review_refresh": review_result,
        "signed_delegation_refresh": remote_result,
        "opportunity_count": len(opportunities),
        "promotable_count": sum(
            1
            for row in opportunities
            if str(row["status"]).startswith("promotable_")
            or str(row["status"]).startswith("reconsider_hard_denial")
        ),
        "hard_denial_opportunity_count": sum(1 for row in opportunities if row["hard_denial_seen"]),
        "unresolved_count": sum(
            1 for row in opportunities if row["status"] == "seek_independent_authority_evidence"
        ),
        "global_rules": {
            "discovery_is_opportunity_not_root_authority": True,
            "hard_denial_requires_new_independent_evidence_for_reconsideration": True,
            "alternate_identity_bypass": False,
            "ordinary_transport_failover_requires_same_existing_authority": True,
        },
        "opportunities": opportunities,
    }
    (state / "authority_opportunity_queue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
