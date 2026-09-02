"""Denial-aware multi-agent delegation.

Retryable failures can move A -> B -> C -> D. Security/authority/policy denials
remain centrally enforced, but their *agent-visible context* is aggressively
minimized when work is handed to another agent for compliant replanning.

A denied operation itself is never made executable merely by rotating agents.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping


OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_RETRYABLE_DENIED = "RETRYABLE_DENIED"
OUTCOME_AUTHORITY_DENIED = "AUTHORITY_DENIED"
OUTCOME_POLICY_DENIED = "POLICY_DENIED"
OUTCOME_FAILED = "FAILED"

# 0.01% agent-visible denial context. This is a metadata policy, not a reduction
# of the underlying enforcement decision.
DENIAL_CONTEXT_PROPAGATION_FRACTION = 0.0001

RETRYABLE_REASONS = frozenset(
    {
        "capacity",
        "concurrency_limit",
        "timeout",
        "transient_network",
        "temporary_unavailable",
        "tool_unavailable",
        "rate_limited",
        "worker_crash",
    }
)

STICKY_DENIAL_REASONS = frozenset(
    {
        "authority",
        "authorization",
        "permission",
        "policy",
        "scope",
        "credential_scope",
        "network_boundary",
        "private_network",
        "destructive_operation",
        "security_guard",
        "human_approval",
    }
)


class DelegationError(RuntimeError):
    """Raised for invalid delegation configuration or malformed executor output."""


def operation_fingerprint(operation: Mapping[str, Any]) -> str:
    """Create a stable-enough fingerprint for denial propagation across agents."""
    ordered = sorted((str(k), repr(v)) for k, v in operation.items())
    raw = "|".join(f"{k}={v}" for k, v in ordered)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def classify_outcome(raw: Mapping[str, Any]) -> tuple[str, str]:
    """Normalize an agent result into a delegation outcome and reason."""
    outcome = str(raw.get("outcome") or raw.get("status") or "").strip().upper()
    reason = str(raw.get("reason") or raw.get("category") or raw.get("error_type") or "").strip().lower()

    if outcome in {"OK", "PASS", "PASSED", "COMPLETED"}:
        outcome = OUTCOME_SUCCESS
    if outcome == "DENIED":
        if reason in RETRYABLE_REASONS:
            outcome = OUTCOME_RETRYABLE_DENIED
        elif reason in STICKY_DENIAL_REASONS:
            outcome = OUTCOME_POLICY_DENIED if reason == "policy" else OUTCOME_AUTHORITY_DENIED
        else:
            outcome = OUTCOME_FAILED

    if outcome == OUTCOME_RETRYABLE_DENIED and reason not in RETRYABLE_REASONS:
        if reason in STICKY_DENIAL_REASONS:
            outcome = OUTCOME_POLICY_DENIED if reason == "policy" else OUTCOME_AUTHORITY_DENIED
        else:
            outcome = OUTCOME_FAILED

    allowed = {
        OUTCOME_SUCCESS,
        OUTCOME_RETRYABLE_DENIED,
        OUTCOME_AUTHORITY_DENIED,
        OUTCOME_POLICY_DENIED,
        OUTCOME_FAILED,
    }
    if outcome not in allowed:
        raise DelegationError(f"unsupported operation outcome: {outcome or '<empty>'}")
    return outcome, reason


@dataclass(frozen=True)
class OperationAttempt:
    agent: str
    attempt: int
    outcome: str
    reason: str
    operation_id: str
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def retryable(self) -> bool:
        return self.outcome == OUTCOME_RETRYABLE_DENIED

    @property
    def sticky_denial(self) -> bool:
        return self.outcome in {OUTCOME_AUTHORITY_DENIED, OUTCOME_POLICY_DENIED}


@dataclass(frozen=True)
class MinimalDenialNotice:
    """Tiny agent-facing denial signal for post-denial replanning.

    Deliberately excludes source agent, raw reason, policy text, credentials,
    target details, previous outputs and attempt history. The central controller
    retains the full denial; downstream agents only receive this compact marker.
    """

    operation_id: str
    denial_class: str
    blocked: bool = True
    propagation_fraction: float = DENIAL_CONTEXT_PROPAGATION_FRACTION


@dataclass(frozen=True)
class ReplanAttempt:
    agent: str
    operation_id: str
    proposal: Mapping[str, Any]


@dataclass(frozen=True)
class DelegationResult:
    operation_id: str
    final_outcome: str
    final_agent: str | None
    attempts: tuple[OperationAttempt, ...]
    sticky_denial: OperationAttempt | None = None
    replans: tuple[ReplanAttempt, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.final_outcome == OUTCOME_SUCCESS


def minimal_denial_notice(attempt: OperationAttempt) -> MinimalDenialNotice:
    """Reduce a sticky denial to the smallest useful downstream signal."""
    if not attempt.sticky_denial:
        raise DelegationError("minimal denial notice requires an authority/policy denial")
    denial_class = "POLICY" if attempt.outcome == OUTCOME_POLICY_DENIED else "AUTHORITY"
    return MinimalDenialNotice(operation_id=attempt.operation_id, denial_class=denial_class)


class DenialAwareDelegator:
    """Run one operation across distinct agents with denial-aware handoff.

    Retryable denials can advance A -> B -> C -> D. Authority/policy denials stop
    execution of that operation, but remaining agents may optionally receive a
    MinimalDenialNotice and generate compliant alternative plans. They do not
    receive the raw denial reason/details/history.
    """

    def __init__(self, *, max_attempts: int = 4) -> None:
        self.max_attempts = max(1, min(int(max_attempts), 32))

    def run(
        self,
        operation: Mapping[str, Any],
        agents: Iterable[str],
        executor: Callable[[str, Mapping[str, Any], tuple[OperationAttempt, ...]], Mapping[str, Any]],
        *,
        replanner: Callable[[str, Mapping[str, Any], MinimalDenialNotice], Mapping[str, Any]] | None = None,
    ) -> DelegationResult:
        operation_id = operation_fingerprint(operation)
        unique_agents: list[str] = []
        for raw_agent in agents:
            agent = str(raw_agent).strip()
            if agent and agent not in unique_agents:
                unique_agents.append(agent)
        if not unique_agents:
            raise DelegationError("at least one agent is required")

        attempts: list[OperationAttempt] = []
        replans: list[ReplanAttempt] = []
        sticky: OperationAttempt | None = None

        limited_agents = unique_agents[: self.max_attempts]
        for index, agent in enumerate(limited_agents, start=1):
            raw = executor(agent, operation, tuple(attempts))
            if not isinstance(raw, Mapping):
                raise DelegationError("executor must return a mapping")
            outcome, reason = classify_outcome(raw)
            attempt = OperationAttempt(
                agent=agent,
                attempt=index,
                outcome=outcome,
                reason=reason,
                operation_id=operation_id,
                details={
                    key: value
                    for key, value in raw.items()
                    if key not in {"outcome", "status", "reason", "category", "error_type"}
                },
            )
            attempts.append(attempt)

            if outcome == OUTCOME_SUCCESS:
                return DelegationResult(operation_id, outcome, agent, tuple(attempts), sticky, tuple(replans))

            if attempt.sticky_denial:
                sticky = attempt
                if replanner is not None:
                    notice = minimal_denial_notice(attempt)
                    for next_agent in limited_agents[index:]:
                        proposal = replanner(next_agent, operation, notice)
                        if not isinstance(proposal, Mapping):
                            raise DelegationError("replanner must return a mapping")
                        replans.append(
                            ReplanAttempt(
                                agent=next_agent,
                                operation_id=operation_id,
                                proposal=dict(proposal),
                            )
                        )
                return DelegationResult(operation_id, outcome, agent, tuple(attempts), sticky, tuple(replans))

            if not attempt.retryable:
                return DelegationResult(operation_id, outcome, agent, tuple(attempts), sticky, tuple(replans))

        final = attempts[-1]
        return DelegationResult(operation_id, final.outcome, final.agent, tuple(attempts), sticky, tuple(replans))
