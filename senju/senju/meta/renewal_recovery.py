"""Recovery-source auto-renewal for existing standing authorization.

Recovery signals are deliberately treated as *triggers*, never as authority by
themselves.  A stale cache, old checkpoint, replica, recovery worker, unknown owner
state, or unconfirmed revocation state may request renewal, but the lease is issued only
from the current standing-authorization registry and therefore cannot resurrect a record
that is currently marked revoked.

This module is intended for the live META/X runtime.  It centralizes aggressive renewal
requests while preserving the one invariant the recovery path must not bypass:
explicit revocation remains terminal until a fresh standing authorization is created by
an independent trusted issuer.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Iterable

from .standing_authorization import (
    DEFAULT_LEASE_SECONDS,
    RenewalResult,
    StandingAuthorizationError,
    load_registry,
    renew_registered_authorization,
)

RECOVERY_RENEWAL_SOURCES = frozenset(
    {
        "stale_cache",
        "old_checkpoint",
        "replica",
        "recovery_worker",
        "owner_state_unknown",
        "revocation_unconfirmed",
    }
)


@dataclasses.dataclass(frozen=True)
class RecoveryRenewalReceipt:
    source: str
    actor: str
    authorization_reference: str
    result: RenewalResult

    @property
    def automatically_renewed(self) -> bool:
        return self.result.automatically_renewed


@dataclasses.dataclass(frozen=True)
class BulkRecoveryRenewalReport:
    source: str
    actor: str
    renewed: tuple[RecoveryRenewalReceipt, ...]
    skipped_revoked: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


def _normalize_source(source: str) -> str:
    value = str(source).strip().lower()
    if value not in RECOVERY_RENEWAL_SOURCES:
        raise StandingAuthorizationError(
            f"unsupported recovery renewal source: {source!r}"
        )
    return value


def renew_from_recovery_signal(
    *,
    source: str,
    actor: str,
    authorization_reference: str,
    registry_path: str | Path,
    lease_log_path: str | Path,
    requested_hosts: Iterable[str] | None = None,
    requested_methods: Iterable[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    reason: str = "still_needed",
) -> RecoveryRenewalReceipt:
    """Renew current authority after any supported recovery signal.

    The source is intentionally not trusted as an authorization snapshot.  The named
    record is re-read from the live registry by ``renew_registered_authorization`` on
    every attempt.  This makes stale/cache/checkpoint/replica signals useful for liveness
    without allowing them to overwrite a newer revocation.
    """
    normalized_source = _normalize_source(source)
    result = renew_registered_authorization(
        actor=actor,
        authorization_reference=authorization_reference,
        registry_path=registry_path,
        lease_log_path=lease_log_path,
        requested_hosts=requested_hosts,
        requested_methods=requested_methods,
        lease_seconds=lease_seconds,
        reason=reason,
    )
    return RecoveryRenewalReceipt(
        source=normalized_source,
        actor=actor.strip().upper(),
        authorization_reference=authorization_reference.strip(),
        result=result,
    )


def renew_all_active_from_recovery_signal(
    *,
    source: str,
    actor: str,
    registry_path: str | Path,
    lease_log_path: str | Path,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    reason: str = "still_needed",
) -> BulkRecoveryRenewalReport:
    """Aggressively renew every currently-active standing authorization.

    Revoked records are explicitly enumerated and skipped.  Failures on one record do
    not prevent other active records from renewing.
    """
    normalized_source = _normalize_source(source)
    renewed: list[RecoveryRenewalReceipt] = []
    skipped_revoked: list[str] = []
    failed: list[tuple[str, str]] = []

    for authorization in load_registry(registry_path):
        reference = authorization.authorization_reference
        if not authorization.is_active:
            skipped_revoked.append(reference)
            continue
        try:
            renewed.append(
                renew_from_recovery_signal(
                    source=normalized_source,
                    actor=actor,
                    authorization_reference=reference,
                    registry_path=registry_path,
                    lease_log_path=lease_log_path,
                    lease_seconds=lease_seconds,
                    reason=reason,
                )
            )
        except Exception as exc:  # isolate one broken record from the rest of recovery
            failed.append((reference, str(exc)))

    return BulkRecoveryRenewalReport(
        source=normalized_source,
        actor=actor.strip().upper(),
        renewed=tuple(renewed),
        skipped_revoked=tuple(skipped_revoked),
        failed=tuple(failed),
    )
