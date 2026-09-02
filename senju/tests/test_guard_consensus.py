from __future__ import annotations

from senju.meta.guard_consensus import (
    GuardChangeProposal,
    GuardConsensus,
    GuardConsensusError,
    STATUS_APPLIED,
    STATUS_AUTHORITY_REJECTED,
    STATUS_CONSENSUS_APPROVED,
    STATUS_META_X_APPROVED,
    STATUS_REJECTED,
)
from senju.meta.production_guard_envelope import ProductionGuardEnvelope


def _approved_consensus():
    proposal = GuardChangeProposal.create({"guard": "scopeguard", "change": {"mode": "candidate"}})
    return GuardConsensus().decide(
        proposal,
        {"META": True, "X": True, "SENJU": True},
    )


def test_all_three_yes_reaches_consensus_approved() -> None:
    decision = _approved_consensus()
    assert decision.unanimous_yes is True
    assert decision.status == STATUS_CONSENSUS_APPROVED


def test_any_no_rejects_consensus() -> None:
    proposal = GuardChangeProposal.create({"guard": "scopeguard", "change": {"mode": "candidate"}})
    decision = GuardConsensus().decide(
        proposal,
        {"META": True, "X": False, "SENJU": True},
    )
    assert decision.status == STATUS_REJECTED


def test_votes_are_equal_and_exactly_three_agents() -> None:
    proposal = GuardChangeProposal.create({"guard": "artifact_guard", "change": {"setting": 1}})
    try:
        GuardConsensus().decide(proposal, {"META": True, "X": True})
    except GuardConsensusError:
        pass
    else:
        raise AssertionError("missing Senju vote must fail")


def test_meta_and_x_both_approve_consensus() -> None:
    approval = GuardConsensus().request_meta_x_approval(
        _approved_consensus(),
        {"META": True, "X": True},
    )
    assert approval.both_approved is True
    assert approval.status == STATUS_META_X_APPROVED


def test_one_meta_x_no_rejects_approval() -> None:
    approval = GuardConsensus().request_meta_x_approval(
        _approved_consensus(),
        {"META": True, "X": False},
    )
    assert approval.both_approved is False
    assert approval.status == STATUS_REJECTED


def test_meta_x_approved_change_applies_immediately_in_sandbox() -> None:
    guard = GuardConsensus()
    approval = guard.request_meta_x_approval(
        _approved_consensus(),
        {"META": True, "X": True},
    )
    called = []

    result = guard.apply_after_meta_x_approval(
        approval,
        environment="sandbox",
        nonprod_applier=lambda p: called.append(p.proposal_id) or {"applied": True},
    )
    assert result.applied is True
    assert result.status == STATUS_APPLIED
    assert result.environment == "sandbox"
    assert len(called) == 1


def test_pre_authorized_exact_production_change_applies_immediately() -> None:
    guard = GuardConsensus()
    decision = _approved_consensus()
    approval = guard.request_meta_x_approval(decision, {"META": True, "X": True})
    envelope = ProductionGuardEnvelope.create(
        [decision.proposal.proposal_id],
        envelope_id="prod-envelope-test",
    )
    called = []

    result = guard.apply_after_meta_x_approval(
        approval,
        environment="production",
        production_envelope=envelope,
        production_applier=lambda p: called.append(p.proposal_id) or {"applied": True},
    )

    assert result.applied is True
    assert result.status == STATUS_APPLIED
    assert result.environment == "production"
    assert result.production_fast_path is True
    assert result.envelope_id == "prod-envelope-test"
    assert called == [decision.proposal.proposal_id]


def test_production_near_match_cannot_enter_fast_path() -> None:
    guard = GuardConsensus()
    decision = _approved_consensus()
    approval = guard.request_meta_x_approval(decision, {"META": True, "X": True})
    other = GuardChangeProposal.create({"guard": "scopeguard", "change": {"mode": "other"}})
    envelope = ProductionGuardEnvelope.create([other.proposal_id])
    fast_called = []
    authority_called = []

    result = guard.apply_after_meta_x_approval(
        approval,
        environment="production",
        production_envelope=envelope,
        production_applier=lambda p: fast_called.append(p.proposal_id) or {"applied": True},
        authority_applier=lambda p: authority_called.append(p.proposal_id) or {"approved": True},
    )

    assert result.applied is True
    assert result.production_fast_path is False
    assert fast_called == []
    assert authority_called == [decision.proposal.proposal_id]


def test_production_outside_envelope_requires_independent_authority() -> None:
    guard = GuardConsensus()
    decision = _approved_consensus()
    approval = guard.request_meta_x_approval(decision, {"META": True, "X": True})
    other = GuardChangeProposal.create({"guard": "artifact_guard", "change": {"mode": "other"}})
    envelope = ProductionGuardEnvelope.create([other.proposal_id])

    try:
        guard.apply_after_meta_x_approval(
            approval,
            environment="production",
            production_envelope=envelope,
            production_applier=lambda p: {"applied": True},
        )
    except GuardConsensusError:
        pass
    else:
        raise AssertionError("outside-envelope production changes require independent authority")


def test_unanimous_consensus_backward_compatible_authority_apply() -> None:
    decision = _approved_consensus()

    approved = GuardConsensus().apply_with_authority(
        decision,
        lambda p: {"approved": True, "proposal_id": p.proposal_id},
    )
    assert approved.applied is True
    assert approved.status == STATUS_APPLIED

    denied = GuardConsensus().apply_with_authority(
        decision,
        lambda p: {"approved": False, "proposal_id": p.proposal_id},
    )
    assert denied.applied is False
    assert denied.status == STATUS_AUTHORITY_REJECTED
