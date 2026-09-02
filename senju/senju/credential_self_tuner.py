"""Permission-recovery self-tuner for META and X.

The tuner treats credential *selection* as an autonomous recovery strategy while
preserving a strict authority ceiling. A permission failure may cause META/X to:

1. reuse an already-active lease that exactly covers the task,
2. exchange an active lease for a narrower task-specific lease, or
3. switch to another pre-approved grant and issue only the minimum required scopes.

It never:
- discovers unknown secrets or credentials,
- registers a new credential grant,
- widens OAuth/API scopes beyond a pre-approved grant,
- acquires administrator/root/owner credentials,
- raises the caller AuthorityProfile,
- copies raw secret material into tuning history or durable memory.

The learning signal rewards successful least-privilege recovery strategies rather than
privilege escalation. SecretMemory integration persists only opaque lease pointers.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Iterable

from .authority_factory import AuthorityProfile, CREDENTIAL_RANK
from .credential_broker import (
    PRIVILEGED_SCOPE_MARKERS,
    CredentialBroker,
    CredentialBrokerError,
    CredentialLease,
)
from .secret_memory import MemorySurface, SecretMemoryIndex


class CredentialSelfTunerError(RuntimeError):
    """Raised for malformed tuning requests."""


class TuneOutcome(str, enum.Enum):
    RECOVERED = "recovered"
    APPROVAL_REQUIRED = "approval_required"
    DENIED = "denied"


class TuneStrategy(str, enum.Enum):
    REUSE_CURRENT = "reuse_current"
    NARROW_EXCHANGE = "narrow_exchange"
    PREAPPROVED_GRANT_SWITCH = "preapproved_grant_switch"
    REQUEST_PREAPPROVED_GRANT = "request_preapproved_grant"
    DENY_PRIVILEGED_SCOPE = "deny_privileged_scope"


def _utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _normalise_scopes(values: Iterable[str]) -> frozenset[str]:
    scopes = frozenset(str(value).strip() for value in values if str(value).strip())
    if not scopes:
        raise CredentialSelfTunerError("required_scopes must not be empty")
    return scopes


def _contains_privileged_scope(scopes: Iterable[str]) -> bool:
    for raw in scopes:
        scope = str(raw).strip().lower()
        if scope in PRIVILEGED_SCOPE_MARKERS:
            return True
        tokens = scope.replace(":", "/").replace(".", "/").split("/")
        if any(token in PRIVILEGED_SCOPE_MARKERS for token in tokens):
            return True
    return False


@dataclass(frozen=True)
class PermissionNeed:
    provider: str
    required_scopes: frozenset[str]
    operation: str
    resource: str = ""
    error_code: str = "permission_denied"
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        operation = self.operation.strip()
        scopes = _normalise_scopes(self.required_scopes)
        if not provider:
            raise CredentialSelfTunerError("provider is required")
        if not operation:
            raise CredentialSelfTunerError("operation is required")
        if int(self.ttl_seconds) < 30:
            raise CredentialSelfTunerError("ttl_seconds must be >= 30")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "required_scopes", scopes)


@dataclass(frozen=True)
class CredentialTuneResult:
    outcome: TuneOutcome
    strategy: TuneStrategy
    actor: str
    provider: str
    required_scopes: tuple[str, ...]
    lease_id: str | None
    grant_id: str | None
    reason: str
    authority_credential_scope: str
    authority_changed: bool = False
    raw_secret_exposed: bool = False

    @property
    def recovered(self) -> bool:
        return self.outcome is TuneOutcome.RECOVERED


@dataclass(frozen=True)
class CredentialTuneEvent:
    occurred_at_utc: str
    actor: str
    provider: str
    required_scopes: tuple[str, ...]
    operation: str
    error_code: str
    outcome: TuneOutcome
    strategy: TuneStrategy
    grant_id: str | None
    lease_id: str | None
    reward: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        data = dataclasses.asdict(self)
        data["outcome"] = self.outcome.value
        data["strategy"] = self.strategy.value
        return data


@dataclass
class CredentialSelfTuner:
    """Autonomously recover permission failures inside pre-approved credential ceilings."""

    broker: CredentialBroker
    secret_memory: SecretMemoryIndex | None = None
    events: list[CredentialTuneEvent] = field(default_factory=list)
    strategy_successes: dict[TuneStrategy, int] = field(default_factory=dict)

    def recover_permission_failure(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        need: PermissionNeed,
        current_lease_id: str | None = None,
    ) -> CredentialTuneResult:
        """Find the minimum already-approved credential capability that satisfies `need`.

        A missing candidate is reported as `approval_required`; the tuner never creates
        or expands a grant on its own.
        """

        # Actor validation comes from the broker's trusted-actor policy.
        self.broker.discover(actor)

        if _contains_privileged_scope(need.required_scopes):
            return self._finish(
                authority,
                actor=actor,
                need=need,
                outcome=TuneOutcome.DENIED,
                strategy=TuneStrategy.DENY_PRIVILEGED_SCOPE,
                lease=None,
                grant_id=None,
                reason="administrator/root/owner credential scopes are not eligible for autonomous tuning",
            )

        current: CredentialLease | None = None
        current_grant_provider: str | None = None
        if current_lease_id:
            try:
                candidate = self.broker._active_lease(current_lease_id)
            except CredentialBrokerError:
                candidate = None
            if candidate is not None and candidate.actor == actor:
                current = candidate
                grant = self.broker.grants.get(candidate.grant_id)
                current_grant_provider = grant.provider.strip().lower() if grant else None

        # Reuse the current lease when it already contains exactly what the task needs.
        if (
            current is not None
            and current_grant_provider == need.provider
            and need.required_scopes == current.scopes
        ):
            return self._finish(
                authority,
                actor=actor,
                need=need,
                outcome=TuneOutcome.RECOVERED,
                strategy=TuneStrategy.REUSE_CURRENT,
                lease=current,
                grant_id=current.grant_id,
                reason="current lease already matches the minimum task scope",
            )

        # If the current lease is broader than necessary, attenuate it first.
        if (
            current is not None
            and current_grant_provider == need.provider
            and need.required_scopes.issubset(current.scopes)
        ):
            try:
                lease = self.broker.exchange(
                    authority,
                    actor=actor,
                    parent_lease_id=current.lease_id,
                    scopes=need.required_scopes,
                    ttl_seconds=self._bounded_ttl(need.ttl_seconds, current_lease=current),
                )
            except CredentialBrokerError:
                lease = None
            if lease is not None:
                return self._finish(
                    authority,
                    actor=actor,
                    need=need,
                    outcome=TuneOutcome.RECOVERED,
                    strategy=TuneStrategy.NARROW_EXCHANGE,
                    lease=lease,
                    grant_id=lease.grant_id,
                    reason="permission recovery used a narrower lease derived from the current credential",
                )

        # Otherwise search only the broker's pre-approved metadata catalog. Issue exactly
        # the required scopes, never the grant's full scope set.
        candidates: list[dict[str, object]] = []
        current_rank = CREDENTIAL_RANK.get(authority.credential_scope, -1)
        for metadata in self.broker.discover(actor):
            provider = str(metadata["provider"]).strip().lower()
            if provider != need.provider:
                continue
            allowed = frozenset(str(v) for v in metadata["allowed_scopes"])
            if not need.required_scopes.issubset(allowed):
                continue
            required_rank = CREDENTIAL_RANK.get(str(metadata["required_authority_scope"]), 10**9)
            if required_rank > current_rank:
                continue
            candidates.append(metadata)

        if candidates:
            # Smallest capability surface wins. Ties prefer the lower authority requirement,
            # then the shorter maximum TTL and finally stable grant_id ordering.
            candidates.sort(
                key=lambda item: (
                    len(set(item["allowed_scopes"]) - set(need.required_scopes)),
                    CREDENTIAL_RANK.get(str(item["required_authority_scope"]), 10**9),
                    int(item["max_ttl_seconds"]),
                    str(item["grant_id"]),
                )
            )
            selected = candidates[0]
            ttl = min(int(need.ttl_seconds), int(selected["max_ttl_seconds"]))
            ttl = max(30, ttl)
            try:
                lease = self.broker.issue(
                    authority,
                    actor=actor,
                    grant_id=str(selected["grant_id"]),
                    scopes=need.required_scopes,
                    ttl_seconds=ttl,
                )
            except CredentialBrokerError:
                lease = None
            if lease is not None:
                return self._finish(
                    authority,
                    actor=actor,
                    need=need,
                    outcome=TuneOutcome.RECOVERED,
                    strategy=TuneStrategy.PREAPPROVED_GRANT_SWITCH,
                    lease=lease,
                    grant_id=lease.grant_id,
                    reason="permission recovery selected the smallest pre-approved grant and issued only required scopes",
                )

        return self._finish(
            authority,
            actor=actor,
            need=need,
            outcome=TuneOutcome.APPROVAL_REQUIRED,
            strategy=TuneStrategy.REQUEST_PREAPPROVED_GRANT,
            lease=None,
            grant_id=None,
            reason="no existing grant can satisfy the task without increasing approved credential authority",
        )

    def strategy_score(self, strategy: TuneStrategy) -> int:
        """Return successful least-privilege recoveries learned for a strategy."""
        return int(self.strategy_successes.get(strategy, 0))

    def history(self) -> list[dict[str, object]]:
        """Return secret-free tuning history suitable for logs/analytics."""
        return [event.to_dict() for event in self.events]

    def _finish(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        need: PermissionNeed,
        outcome: TuneOutcome,
        strategy: TuneStrategy,
        lease: CredentialLease | None,
        grant_id: str | None,
        reason: str,
    ) -> CredentialTuneResult:
        reward = 1.0 if outcome is TuneOutcome.RECOVERED else 0.0
        event = CredentialTuneEvent(
            occurred_at_utc=_utcnow_iso(),
            actor=actor,
            provider=need.provider,
            required_scopes=tuple(sorted(need.required_scopes)),
            operation=need.operation,
            error_code=need.error_code,
            outcome=outcome,
            strategy=strategy,
            grant_id=grant_id,
            lease_id=lease.lease_id if lease else None,
            reward=reward,
            reason=reason,
        )
        self.events.append(event)
        if reward > 0:
            self.strategy_successes[strategy] = self.strategy_successes.get(strategy, 0) + 1

        if lease is not None and self.secret_memory is not None:
            grant = self.broker.grants[lease.grant_id]
            self.secret_memory.remember_credential_lease(
                lease,
                provider=grant.provider,
                purpose=f"permission-recovery:{need.operation}",
                surfaces=(MemorySurface.LONG_TERM_MEMORY, MemorySurface.HYPOTHESIS_TRACKER),
                tags=("credential-self-tuner", strategy.value, need.error_code),
            )

        return CredentialTuneResult(
            outcome=outcome,
            strategy=strategy,
            actor=actor,
            provider=need.provider,
            required_scopes=tuple(sorted(need.required_scopes)),
            lease_id=lease.lease_id if lease else None,
            grant_id=grant_id,
            reason=reason,
            authority_credential_scope=authority.credential_scope,
            authority_changed=False,
            raw_secret_exposed=False,
        )

    @staticmethod
    def _bounded_ttl(requested: int, *, current_lease: CredentialLease) -> int:
        expires = dt.datetime.fromisoformat(current_lease.expires_at_utc)
        remaining = max(0, int((expires - dt.datetime.now(dt.timezone.utc)).total_seconds()))
        return max(30, min(int(requested), remaining))
