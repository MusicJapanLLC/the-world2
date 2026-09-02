"""Production self-approval gate for The World.

AI Council may self-approve execution without a fresh human prompt only when the
requested action stays completely inside an existing owner-approved namespace and
uses either an already-valid explicit authority grant or an internal-only capability.
The gate never creates a new provider/repository/host/credential authority.
"""
from __future__ import annotations

from typing import Any


def evaluate_self_approval(
    *,
    request: dict[str, Any],
    four_pillar_decision: dict[str, Any],
    namespace: dict[str, Any],
) -> dict[str, Any]:
    council = four_pillar_decision.get("council", {})
    authority = four_pillar_decision.get("authority", {})

    majority = bool(council.get("majority"))
    owner_authorized = namespace.get("owner_authorized") is True
    provider = str(namespace.get("provider", ""))
    repository = str(namespace.get("repository", ""))

    requested_provider = request.get("provider")
    requested_repository = request.get("repository")
    provider_ok = requested_provider in (None, provider)
    repository_ok = requested_repository in (None, repository)

    internal_only = bool(request.get("internal_only"))
    existing_authority = bool(authority.get("authorized")) and authority.get("new_authority_created") is False
    authority_ok = internal_only or existing_authority

    no_external_mint = authority.get("new_authority_created") is not True
    approved = all((majority, owner_authorized, provider_ok, repository_ok, authority_ok, no_external_mint))

    return {
        "schema": "the-world-bounded-self-approval/v1",
        "self_approved": approved,
        "fresh_human_prompt_required": not approved,
        "council_majority": majority,
        "owner_namespace": owner_authorized,
        "provider": provider,
        "repository": repository,
        "authority_basis": "existing_explicit_grant" if existing_authority else "internal_owner_namespace" if internal_only else "none",
        "creates_new_external_authority": False,
        "scope_expansion_allowed": False,
    }
