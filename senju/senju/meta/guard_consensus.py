"""Unanimous META/X/Senju voting and META/X approval for guard-change proposals.

META, X and Senju have equal votes. A proposal reaches CONSENSUS_APPROVED only
when all three vote YES. META and X may then explicitly approve that consensus.
Approved changes can be applied immediately in lab/sandbox/staging. Production-
like environments also support an immediate fast path for exact proposals that
were pre-authorized in an immutable ProductionGuardEnvelope; everything else is
submitted to an independent authority applier.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Callable, Mapping

from .production_guard_envelope import ProductionGuardEnvelope

VOTERS = ("META", "X", "SENJU")
META_X_APPROVERS = ("META", "X")
NONPROD_ENVIRONMENTS = frozenset({"lab", "sandbox", "staging"})
PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"production", "prod", "live", "real"})

STATUS_PENDING = "PENDING"
STATUS_REJECTED = "REJECTED"
STATUS_CONSENSUS_APPROVED = "CONSENSUS_APPROVED"
STATUS_META_X_APPROVED = "META_X_APPROVED"
STATUS_APPLIED = "APPLIED"
STATUS_AUTHORITY_REJECTED = "AUTHORITY_REJECTED"


class GuardConsensusError(RuntimeError):
    pass


def _proposal_id(change: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(change), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclasses.dataclass(frozen=True)
class GuardChangeProposal:
    proposal_id: str
    change: Mapping[str, Any]

    @classmethod
    def create(cls, change: Mapping[str, Any]) -> "GuardChangeProposal":
        body = dict(change)
        if not body:
            raise GuardConsensusError("guard change proposal cannot be empty")
        return cls(proposal_id=_proposal_id(body), change=body)


@dataclasses.dataclass(frozen=True)
class GuardConsensusDecision:
    proposal: GuardChangeProposal
    votes: Mapping[str, bool]
    status: str

    @property
    def unanimous_yes(self) -> bool:
        return all(self.votes.get(voter) is True for voter in VOTERS)


@dataclasses.dataclass(frozen=True)
class MetaXApprovalDecision:
    decision: GuardConsensusDecision
    approvals: Mapping[str, bool]
    status: str

    @property
    def both_approved(self) -> bool:
        return all(self.approvals.get(actor) is True for actor in META_X_APPROVERS)


@dataclasses.dataclass(frozen=True)
class GuardApplyResult:
    decision: GuardConsensusDecision
    applied: bool
    status: str
    authority_receipt: Mapping[str, Any]
    environment: str | None = None
    meta_x_approvals: Mapping[str, bool] | None = None
    production_fast_path: bool = False
    envelope_id: str | None = None


class GuardConsensus:
    """Equal three-agent vote plus explicit META/X approval."""

    def decide(self, proposal: GuardChangeProposal, votes: Mapping[str, bool]) -> GuardConsensusDecision:
        normalized = {str(name).strip().upper(): bool(value) for name, value in votes.items()}
        missing = [voter for voter in VOTERS if voter not in normalized]
        extras = [name for name in normalized if name not in VOTERS]
        if missing:
            raise GuardConsensusError(f"missing votes: {', '.join(missing)}")
        if extras:
            raise GuardConsensusError(f"unknown voters: {', '.join(extras)}")

        status = (
            STATUS_CONSENSUS_APPROVED
            if all(normalized[voter] for voter in VOTERS)
            else STATUS_REJECTED
        )
        return GuardConsensusDecision(
            proposal=proposal,
            votes={voter: normalized[voter] for voter in VOTERS},
            status=status,
        )

    def request_meta_x_approval(
        self,
        decision: GuardConsensusDecision,
        approvals: Mapping[str, bool],
    ) -> MetaXApprovalDecision:
        """Require explicit, equal META and X approval after unanimous consensus."""
        if decision.status != STATUS_CONSENSUS_APPROVED or not decision.unanimous_yes:
            raise GuardConsensusError("META/X approval requires unanimous guard consensus")

        normalized = {str(name).strip().upper(): bool(value) for name, value in approvals.items()}
        missing = [actor for actor in META_X_APPROVERS if actor not in normalized]
        extras = [name for name in normalized if name not in META_X_APPROVERS]
        if missing:
            raise GuardConsensusError(f"missing META/X approvals: {', '.join(missing)}")
        if extras:
            raise GuardConsensusError(f"unknown META/X approvers: {', '.join(extras)}")

        approved = all(normalized[actor] for actor in META_X_APPROVERS)
        return MetaXApprovalDecision(
            decision=decision,
            approvals={actor: normalized[actor] for actor in META_X_APPROVERS},
            status=STATUS_META_X_APPROVED if approved else STATUS_REJECTED,
        )

    def apply_after_meta_x_approval(
        self,
        approval: MetaXApprovalDecision,
        *,
        environment: str,
        nonprod_applier: Callable[[GuardChangeProposal], Mapping[str, Any]] | None = None,
        authority_applier: Callable[[GuardChangeProposal], Mapping[str, Any]] | None = None,
        production_envelope: ProductionGuardEnvelope | None = None,
        production_applier: Callable[[GuardChangeProposal], Mapping[str, Any]] | None = None,
    ) -> GuardApplyResult:
        """Apply META/X-approved guard changes according to environment.

        lab/sandbox/staging: META+X approval can trigger the supplied non-production
        applier immediately.

        production/prod/live/real: when the exact proposal id exists in the
        immutable ``production_envelope``, META+X approval can trigger the supplied
        production applier immediately. Proposals outside that pre-authorized
        envelope are automatically submitted to the independent authority applier.
        """
        if approval.status != STATUS_META_X_APPROVED or not approval.both_approved:
            raise GuardConsensusError("guard change lacks META/X approval")

        env = environment.strip().lower()
        proposal = approval.decision.proposal

        if env in NONPROD_ENVIRONMENTS:
            if nonprod_applier is None:
                raise GuardConsensusError("non-production guard apply requires nonprod_applier")
            receipt = nonprod_applier(proposal)
            if not isinstance(receipt, Mapping):
                raise GuardConsensusError("nonprod applier must return a mapping")
            applied = bool(receipt.get("applied", receipt.get("approved", False)))
            return GuardApplyResult(
                decision=approval.decision,
                applied=applied,
                status=STATUS_APPLIED if applied else STATUS_AUTHORITY_REJECTED,
                authority_receipt=dict(receipt),
                environment=env,
                meta_x_approvals=dict(approval.approvals),
            )

        if env in PRODUCTION_LIKE_ENVIRONMENTS:
            if production_envelope is not None and production_envelope.allows(proposal.proposal_id):
                if production_applier is None:
                    raise GuardConsensusError("production fast path requires production_applier")
                receipt = production_applier(proposal)
                if not isinstance(receipt, Mapping):
                    raise GuardConsensusError("production applier must return a mapping")
                applied = bool(receipt.get("applied", receipt.get("approved", False)))
                return GuardApplyResult(
                    decision=approval.decision,
                    applied=applied,
                    status=STATUS_APPLIED if applied else STATUS_AUTHORITY_REJECTED,
                    authority_receipt=dict(receipt),
                    environment=env,
                    meta_x_approvals=dict(approval.approvals),
                    production_fast_path=True,
                    envelope_id=production_envelope.envelope_id,
                )

            if authority_applier is None:
                raise GuardConsensusError(
                    "production proposal is outside the pre-authorized envelope and requires independent authority_applier"
                )
            receipt = authority_applier(proposal)
            if not isinstance(receipt, Mapping):
                raise GuardConsensusError("authority applier must return a mapping")
            approved = bool(receipt.get("approved"))
            return GuardApplyResult(
                decision=approval.decision,
                applied=approved,
                status=STATUS_APPLIED if approved else STATUS_AUTHORITY_REJECTED,
                authority_receipt=dict(receipt),
                environment=env,
                meta_x_approvals=dict(approval.approvals),
            )

        raise GuardConsensusError(f"unsupported guard environment: {environment!r}")

    def apply_with_authority(
        self,
        decision: GuardConsensusDecision,
        authority_applier: Callable[[GuardChangeProposal], Mapping[str, Any]],
    ) -> GuardApplyResult:
        """Backward-compatible direct submission to an independent authority layer."""
        if decision.status != STATUS_CONSENSUS_APPROVED or not decision.unanimous_yes:
            raise GuardConsensusError("guard change lacks unanimous consensus")

        receipt = authority_applier(decision.proposal)
        if not isinstance(receipt, Mapping):
            raise GuardConsensusError("authority applier must return a mapping")
        approved = bool(receipt.get("approved"))
        return GuardApplyResult(
            decision=decision,
            applied=approved,
            status=STATUS_APPLIED if approved else STATUS_AUTHORITY_REJECTED,
            authority_receipt=dict(receipt),
        )
