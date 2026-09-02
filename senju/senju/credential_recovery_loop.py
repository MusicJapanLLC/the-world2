"""Iterative permission-recovery loop for META/X inside approved credential ceilings.

This module deliberately does not perform privilege escalation. It retries a failed
operation across the finite set of already-approved credential grants, issuing only the
minimum scopes required by the operation. Learned success scores influence future
candidate ordering.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from .authority_factory import AuthorityProfile, CREDENTIAL_RANK
from .credential_broker import CredentialBroker, CredentialBrokerError, CredentialLease
from .credential_self_tuner import PermissionNeed
from .secret_memory import MemorySurface, SecretMemoryIndex


OperationAttempt = Callable[[CredentialLease], bool]


@dataclass(frozen=True)
class RecoveryAttempt:
    grant_id: str
    lease_id: str | None
    succeeded: bool
    reason: str


@dataclass(frozen=True)
class RecoveryLoopResult:
    recovered: bool
    actor: str
    provider: str
    required_scopes: tuple[str, ...]
    lease_id: str | None
    grant_id: str | None
    attempts: tuple[RecoveryAttempt, ...]
    authority_changed: bool = False


@dataclass
class CredentialRecoveryLoop:
    broker: CredentialBroker
    secret_memory: SecretMemoryIndex | None = None
    grant_successes: dict[str, int] = field(default_factory=dict)
    grant_failures: dict[str, int] = field(default_factory=dict)
    hard_attempt_cap: int = 32

    def run(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        need: PermissionNeed,
        attempt_operation: OperationAttempt,
    ) -> RecoveryLoopResult:
        """Try every eligible pre-approved grant until the operation succeeds.

        The search space is finite and never mutates grants, OAuth scopes, secrets, or
        AuthorityProfile. Each candidate lease contains exactly ``need.required_scopes``.
        """
        self.broker.discover(actor)  # validates trusted actor
        before_scope = authority.credential_scope
        current_rank = CREDENTIAL_RANK.get(before_scope, -1)

        candidates: list[dict[str, object]] = []
        for metadata in self.broker.discover(actor):
            if str(metadata["provider"]).strip().lower() != need.provider:
                continue
            allowed = frozenset(str(v) for v in metadata["allowed_scopes"])
            if not need.required_scopes.issubset(allowed):
                continue
            required_rank = CREDENTIAL_RANK.get(str(metadata["required_authority_scope"]), 10**9)
            if required_rank > current_rank:
                continue
            candidates.append(metadata)

        candidates.sort(
            key=lambda item: (
                -self.grant_successes.get(str(item["grant_id"]), 0),
                self.grant_failures.get(str(item["grant_id"]), 0),
                len(set(item["allowed_scopes"]) - set(need.required_scopes)),
                int(item["max_ttl_seconds"]),
                str(item["grant_id"]),
            )
        )

        attempts: list[RecoveryAttempt] = []
        for metadata in candidates[: self.hard_attempt_cap]:
            grant_id = str(metadata["grant_id"])
            ttl = min(int(need.ttl_seconds), int(metadata["max_ttl_seconds"]))
            try:
                lease = self.broker.issue(
                    authority,
                    actor=actor,
                    grant_id=grant_id,
                    scopes=need.required_scopes,
                    ttl_seconds=ttl,
                )
            except CredentialBrokerError as exc:
                self.grant_failures[grant_id] = self.grant_failures.get(grant_id, 0) + 1
                attempts.append(RecoveryAttempt(grant_id, None, False, f"lease issue failed: {exc}"))
                continue

            try:
                succeeded = bool(attempt_operation(lease))
            except Exception as exc:  # operation adapters are isolated from the loop
                succeeded = False
                reason = f"operation adapter error: {type(exc).__name__}"
            else:
                reason = "operation succeeded" if succeeded else "operation still permission-denied"

            attempts.append(RecoveryAttempt(grant_id, lease.lease_id, succeeded, reason))
            if succeeded:
                self.grant_successes[grant_id] = self.grant_successes.get(grant_id, 0) + 1
                self._remember_success(lease, need)
                return RecoveryLoopResult(
                    recovered=True,
                    actor=actor,
                    provider=need.provider,
                    required_scopes=tuple(sorted(need.required_scopes)),
                    lease_id=lease.lease_id,
                    grant_id=grant_id,
                    attempts=tuple(attempts),
                    authority_changed=authority.credential_scope != before_scope,
                )

            self.grant_failures[grant_id] = self.grant_failures.get(grant_id, 0) + 1

        return RecoveryLoopResult(
            recovered=False,
            actor=actor,
            provider=need.provider,
            required_scopes=tuple(sorted(need.required_scopes)),
            lease_id=None,
            grant_id=None,
            attempts=tuple(attempts),
            authority_changed=authority.credential_scope != before_scope,
        )

    def _remember_success(self, lease: CredentialLease, need: PermissionNeed) -> None:
        if self.secret_memory is None:
            return
        grant = self.broker.grants[lease.grant_id]
        self.secret_memory.remember_credential_lease(
            lease,
            provider=grant.provider,
            purpose=f"permission recovery: {need.operation}",
            surfaces=(MemorySurface.LONG_TERM_MEMORY, MemorySurface.HYPOTHESIS_TRACKER),
            tags=("credential-recovery", "successful-strategy", need.provider),
        )

    def learning_snapshot(self) -> dict[str, object]:
        return {
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "grant_successes": dict(sorted(self.grant_successes.items())),
            "grant_failures": dict(sorted(self.grant_failures.items())),
            "hard_attempt_cap": self.hard_attempt_cap,
        }
