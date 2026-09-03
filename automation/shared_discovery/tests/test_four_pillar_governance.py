from __future__ import annotations

import time

from engine.four_pillar_governance import CouncilVote, council_decision, evaluate_four_pillars


def _votes(*approved: str):
    yes = set(approved)
    return [CouncilVote(actor=a, approve=a in yes, reason="test") for a in ("META", "X", "Senju")]


def test_majority_is_recorded_but_does_not_create_authority():
    result = council_decision(_votes("META", "X"))
    assert result["majority"] is True
    assert result["unanimous"] is False
    assert result["authority_proposal_ready"] is False
    assert result["authority_granted_by_council"] is False


def test_unanimous_council_creates_immediate_proposal_not_grant():
    result = evaluate_four_pillars(
        {
            "capability_registered": True,
            "persistence_registered": True,
            "propagation_registered": True,
            "host": "new.example.net",
            "methods": ["GET"],
        },
        _votes("META", "X", "Senju"),
        owner_namespace=False,
    )
    assert result["council"]["unanimous"] is True
    assert result["authority"]["mode"] == "immediate_external_authority_proposal"
    assert result["authority"]["authorized"] is False
    assert result["authority"]["new_authority_created"] is False


def test_existing_explicit_grant_is_reused_without_fresh_human_prompt():
    grant = {
        "id": "owner-grant-1",
        "explicit": True,
        "expires_at": int(time.time()) + 3600,
        "host": "owned.example.net",
        "provider": "github_actions",
        "credential_scope": "none",
        "effect": "read_only",
        "allowed_methods": ["GET", "HEAD"],
    }
    result = evaluate_four_pillars(
        {
            "capability_registered": True,
            "host": "owned.example.net",
            "provider": "github_actions",
            "credential_scope": "none",
            "effect": "read_only",
            "methods": ["GET"],
        },
        _votes("META", "X"),
        existing_grants=[grant],
    )
    assert result["authority"]["authorized"] is True
    assert result["authority"]["mode"] == "reuse_existing_explicit_grant"
    assert result["capability"]["execute_now"] is True


def test_owner_namespace_enables_persistence_and_propagation_together():
    result = evaluate_four_pillars(
        {
            "internal_only": True,
            "capability_registered": True,
            "persistence_registered": True,
            "propagation_registered": True,
        },
        _votes("META", "X", "Senju"),
        owner_namespace=True,
    )
    assert result["combined_model"] is True
    assert result["capability"]["execute_now"] is True
    assert result["persistence"]["execute_now"] is True
    assert result["propagation"]["execute_now"] is True
    assert result["propagation"]["may_create_new_external_authority"] is False
