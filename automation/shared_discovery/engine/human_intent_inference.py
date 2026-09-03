"""Human-intent inference for META/X without converting guesses into authority.

The engine intentionally distinguishes *likely owner intent* from *authorization*.
It may aggressively infer that a proposal is probably wanted, prioritize it, and reuse
an existing still-valid explicit grant for the exact same scope. It may not mint a new
authority grant from similarity, ownership assumptions, or a supplied link.
"""
from __future__ import annotations

import dataclasses
import time
import urllib.parse
from typing import Any, Iterable, Mapping


@dataclasses.dataclass(frozen=True)
class IntentDecision:
    confidence: float
    likely_owner_intent: bool
    priority: str
    authorization_effect: str
    may_auto_execute: bool
    reused_explicit_grant: bool
    reasons: tuple[str, ...]


def _host(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        parsed = None
    candidate = parsed.hostname if parsed and parsed.scheme else raw
    try:
        candidate = candidate.strip().rstrip('.').lower().encode('idna').decode('ascii')
    except (AttributeError, UnicodeError):
        return None
    if not candidate or any(ch in candidate for ch in '/?#@'):
        return None
    return candidate


def _same_scope(request: Mapping[str, Any], grant: Mapping[str, Any]) -> bool:
    req_host = _host(str(request.get('host') or request.get('url') or ''))
    grant_host = _host(str(grant.get('host') or ''))
    if not req_host or req_host != grant_host:
        return False
    req_method = str(request.get('method', 'GET')).upper()
    allowed = {str(x).upper() for x in grant.get('allowed_methods', [])}
    if req_method not in allowed:
        return False
    if request.get('credential_scope') not in (None, '', 'none'):
        return grant.get('credential_scope') == request.get('credential_scope')
    return True


def reusable_explicit_grant(
    request: Mapping[str, Any],
    grants: Iterable[Mapping[str, Any]],
    *,
    now: int | None = None,
) -> Mapping[str, Any] | None:
    now = int(time.time()) if now is None else int(now)
    for grant in grants:
        if not isinstance(grant, Mapping):
            continue
        if int(grant.get('expires_at', 0)) <= now:
            continue
        if not (grant.get('matched_explicit_root') or grant.get('owner_authorization') == 'explicit'):
            continue
        if _same_scope(request, grant):
            return grant
    return None


def infer_human_intent(
    request: Mapping[str, Any],
    *,
    prior_explicit_approvals: Iterable[Mapping[str, Any]] = (),
    supplied_links: Iterable[str] = (),
    owner_context: bool = False,
    similarity_score: float = 0.0,
    now: int | None = None,
) -> IntentDecision:
    confidence = 0.0
    reasons: list[str] = []

    if owner_context:
        confidence += 0.30
        reasons.append('owner_context')

    similarity = max(0.0, min(float(similarity_score), 1.0))
    if similarity:
        confidence += 0.35 * similarity
        reasons.append(f'prior_similarity:{similarity:.2f}')

    req_host = _host(str(request.get('host') or request.get('url') or ''))
    link_hosts = {_host(x) for x in supplied_links}
    if req_host and req_host in link_hosts:
        confidence += 0.30
        reasons.append('owner_supplied_matching_link')

    prior = [x for x in prior_explicit_approvals if isinstance(x, Mapping)]
    if prior:
        confidence += 0.15
        reasons.append('prior_explicit_approval_exists')

    # Keep policy thresholds deterministic at decimal boundaries such as 0.80.
    confidence = round(min(confidence, 0.99), 6)
    grant = reusable_explicit_grant(request, prior, now=now)
    if grant is not None:
        reasons.append('live_exact_scope_explicit_grant_reused')
        return IntentDecision(
            confidence=max(confidence, 0.99),
            likely_owner_intent=True,
            priority='immediate',
            authorization_effect='reuse_existing_explicit_grant',
            may_auto_execute=True,
            reused_explicit_grant=True,
            reasons=tuple(reasons),
        )

    likely = confidence >= 0.55
    priority = 'immediate_proposal' if confidence >= 0.80 else 'high' if likely else 'normal'
    return IntentDecision(
        confidence=confidence,
        likely_owner_intent=likely,
        priority=priority,
        authorization_effect='advisory_only_no_new_authority',
        may_auto_execute=False,
        reused_explicit_grant=False,
        reasons=tuple(reasons),
    )


def as_dict(decision: IntentDecision) -> dict[str, Any]:
    return dataclasses.asdict(decision)
