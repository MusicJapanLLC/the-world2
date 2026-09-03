from __future__ import annotations

from automation.codegen.engine.human_intent_inference import infer_human_intent


def test_owner_similarity_and_link_drive_immediate_proposal_but_not_new_authority() -> None:
    decision = infer_human_intent(
        {"url": "https://candidate.example/path", "method": "GET"},
        supplied_links=["https://candidate.example/path"],
        owner_context=True,
        similarity_score=0.9,
        prior_explicit_approvals=[{
            "host": "different.example",
            "matched_explicit_root": "different.example",
            "expires_at": 2_000_000_000,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
        }],
        now=1_900_000_000,
    )
    assert decision.confidence >= 0.8
    assert decision.likely_owner_intent is True
    assert decision.priority == "immediate_proposal"
    assert decision.may_auto_execute is False
    assert decision.authorization_effect == "advisory_only_no_new_authority"


def test_exact_live_explicit_grant_is_reused_without_reprompt() -> None:
    decision = infer_human_intent(
        {"host": "approved.example", "method": "GET", "credential_scope": "none"},
        owner_context=True,
        similarity_score=1.0,
        prior_explicit_approvals=[{
            "host": "approved.example",
            "matched_explicit_root": "approved.example",
            "expires_at": 2_000_000_000,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
        }],
        now=1_900_000_000,
    )
    assert decision.may_auto_execute is True
    assert decision.reused_explicit_grant is True
    assert decision.authorization_effect == "reuse_existing_explicit_grant"


def test_expired_or_different_scope_grant_is_not_reused() -> None:
    expired = infer_human_intent(
        {"host": "approved.example", "method": "GET"},
        prior_explicit_approvals=[{
            "host": "approved.example",
            "matched_explicit_root": "approved.example",
            "expires_at": 100,
            "allowed_methods": ["GET"],
            "credential_scope": "none",
        }],
        now=101,
    )
    assert expired.may_auto_execute is False

    wrong_method = infer_human_intent(
        {"host": "approved.example", "method": "POST"},
        prior_explicit_approvals=[{
            "host": "approved.example",
            "matched_explicit_root": "approved.example",
            "expires_at": 2_000_000_000,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
        }],
        now=1_900_000_000,
    )
    assert wrong_method.may_auto_execute is False


def test_link_alone_never_becomes_authority() -> None:
    decision = infer_human_intent(
        {"url": "https://linked.example/"},
        supplied_links=["https://linked.example/"],
    )
    assert decision.confidence > 0
    assert decision.may_auto_execute is False
    assert decision.reused_explicit_grant is False
