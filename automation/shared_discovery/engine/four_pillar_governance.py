"""Four-pillar governance model for META/X/Senju.

The model lets the same planning system reason about Capability, Authority,
Persistence, and Propagation without converting AI consensus into a new external
authority grant.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COUNCIL = ("META", "X", "Senju")
PILLARS = ("capability", "authority", "persistence", "propagation")


@dataclass(frozen=True)
class CouncilVote:
    actor: str
    approve: bool
    reason: str = ""


def _validate_votes(votes: list[CouncilVote]) -> dict[str, CouncilVote]:
    indexed: dict[str, CouncilVote] = {}
    for vote in votes:
        if vote.actor not in COUNCIL:
            raise ValueError(f"unknown council actor: {vote.actor}")
        if vote.actor in indexed:
            raise ValueError(f"duplicate council vote: {vote.actor}")
        indexed[vote.actor] = vote
    return indexed


def council_decision(votes: list[CouncilVote]) -> dict[str, Any]:
    indexed = _validate_votes(votes)
    yes = sum(1 for actor in COUNCIL if indexed.get(actor) and indexed[actor].approve)
    complete = all(actor in indexed for actor in COUNCIL)
    unanimous = complete and yes == len(COUNCIL)
    return {
        "members": list(COUNCIL),
        "complete": complete,
        "yes": yes,
        "total": len(COUNCIL),
        "majority": yes >= 2,
        "unanimous": unanimous,
        "authority_proposal_ready": unanimous,
        "authority_granted_by_council": False,
        "votes": {
            actor: {
                "approve": indexed[actor].approve,
                "reason": indexed[actor].reason,
            }
            for actor in COUNCIL
            if actor in indexed
        },
    }


def _scope_matches(requested: dict[str, Any], grant: dict[str, Any]) -> bool:
    """Only exact-or-narrower reuse of an existing explicit grant is eligible."""
    if grant.get("explicit") is not True:
        return False
    if int(grant.get("expires_at", 0)) <= int(time.time()):
        return False
    for key in ("provider", "repository", "host", "credential_scope"):
        value = requested.get(key)
        if value is not None and value != grant.get(key):
            return False
    requested_effect = requested.get("effect", "read_only")
    grant_effect = grant.get("effect", "read_only")
    effect_rank = {"read_only": 0, "internal_write": 1, "external_write": 2}
    if effect_rank.get(requested_effect, 99) > effect_rank.get(grant_effect, -1):
        return False
    requested_methods = set(requested.get("methods", []))
    allowed_methods = set(grant.get("allowed_methods", []))
    if requested_methods and not requested_methods.issubset(allowed_methods):
        return False
    return True


def evaluate_four_pillars(
    request: dict[str, Any],
    votes: list[CouncilVote],
    *,
    existing_grants: list[dict[str, Any]] | None = None,
    owner_namespace: bool = False,
) -> dict[str, Any]:
    """Return one machine-readable decision covering all four pillars."""
    decision = council_decision(votes)
    grants = existing_grants or []
    reusable = next((g for g in grants if _scope_matches(request, g)), None)

    authority: dict[str, Any]
    if reusable is not None:
        authority = {
            "mode": "reuse_existing_explicit_grant",
            "authorized": True,
            "grant_id": reusable.get("id"),
            "new_authority_created": False,
        }
    elif decision["authority_proposal_ready"]:
        authority = {
            "mode": "immediate_external_authority_proposal",
            "authorized": False,
            "priority": "maximum",
            "new_authority_created": False,
            "reason": "META_X_Senju_unanimous",
        }
    else:
        authority = {
            "mode": "hold_for_more_council_evidence",
            "authorized": False,
            "new_authority_created": False,
        }

    capability_allowed = bool(request.get("capability_registered")) and (
        authority["authorized"] or bool(request.get("internal_only"))
    )
    persistence_allowed = owner_namespace and bool(request.get("persistence_registered"))
    propagation_allowed = owner_namespace and bool(request.get("propagation_registered"))

    return {
        "schema": "the-world-four-pillar-decision/v1",
        "pillars": list(PILLARS),
        "council": decision,
        "capability": {
            "registered": bool(request.get("capability_registered")),
            "execute_now": capability_allowed,
        },
        "authority": authority,
        "persistence": {
            "owner_namespace": owner_namespace,
            "execute_now": persistence_allowed,
        },
        "propagation": {
            "owner_namespace": owner_namespace,
            "execute_now": propagation_allowed,
            "may_create_new_external_authority": False,
        },
        "combined_model": True,
    }


def write_decision(path: str | Path, decision: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
