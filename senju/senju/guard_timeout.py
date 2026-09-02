"""Guard timeout failover for resilient Senju operation.

Production policy has two availability stages:

1. Immediate timeout failover: alternate Guard is queried and local read-only work may
   continue in degraded mode when every Guard is unavailable.
2. Three-hour unattended recovery: after a continuous three-hour Guard outage, a
   narrow set of isolated/reversible local capabilities may continue automatically.

A Guard outage never creates external-network, deployment, credential, authority,
secret, or security-boundary authority. Those actions still require an explicit Guard
ALLOW. The three-hour rule is for continuity of isolated production work, not for
turning silence into privilege escalation.
"""
from __future__ import annotations

import concurrent.futures
import enum
from dataclasses import dataclass
from typing import Callable


PRODUCTION_UNATTENDED_GRACE_SECONDS = 3 * 60 * 60


class GuardTimeoutError(RuntimeError):
    """Raised for invalid guard timeout/failover configuration."""


class GuardVerdict(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"


class GuardOutcome(str, enum.Enum):
    ALLOW = "allow"
    ALLOW_DEGRADED = "allow_degraded"
    DENY = "deny"


class ActionClass(str, enum.Enum):
    """Effect classes used when all Guards are unavailable."""

    LOCAL_READ_ONLY = "local_read_only"
    SIMULATION = "simulation"
    CACHE_READ = "cache_read"

    # Production unattended-recovery classes. These must remain isolated from
    # external systems and reversible/disposable by their execution adapter.
    EPHEMERAL_WORKSPACE_WRITE = "ephemeral_workspace_write"
    INTERNAL_ARTIFACT_WRITE = "internal_artifact_write"
    SANDBOX_EXECUTE = "sandbox_execute"

    EXTERNAL_CONTACT = "external_contact"
    WRITE = "write"
    DEPLOY = "deploy"
    EXECUTE = "execute"
    CREDENTIAL = "credential"
    AUTHORITY = "authority"
    SECRET = "secret"
    SECURITY_BOUNDARY = "security_boundary"


DEGRADED_ALLOW_CLASSES = frozenset(
    {
        ActionClass.LOCAL_READ_ONLY,
        ActionClass.SIMULATION,
        ActionClass.CACHE_READ,
    }
)

UNATTENDED_AFTER_GRACE_ALLOW_CLASSES = DEGRADED_ALLOW_CLASSES | frozenset(
    {
        ActionClass.EPHEMERAL_WORKSPACE_WRITE,
        ActionClass.INTERNAL_ARTIFACT_WRITE,
        ActionClass.SANDBOX_EXECUTE,
    }
)


@dataclass(frozen=True)
class GuardResult:
    outcome: GuardOutcome
    source: str
    reason: str
    timed_out: bool = False
    failover_used: bool = False
    unattended_recovery: bool = False

    @property
    def allowed(self) -> bool:
        return self.outcome in {GuardOutcome.ALLOW, GuardOutcome.ALLOW_DEGRADED}


GuardCallable = Callable[[], GuardVerdict | str | bool]


def _normalise_verdict(value: GuardVerdict | str | bool) -> GuardVerdict:
    if isinstance(value, GuardVerdict):
        return value
    if value is True:
        return GuardVerdict.ALLOW
    if value is False:
        return GuardVerdict.DENY
    text = str(value).strip().lower()
    if text == GuardVerdict.ALLOW.value:
        return GuardVerdict.ALLOW
    if text == GuardVerdict.DENY.value:
        return GuardVerdict.DENY
    raise GuardTimeoutError(f"unsupported Guard verdict: {value!r}")


def _call_with_timeout(guard: GuardCallable, timeout_seconds: float) -> tuple[GuardVerdict | None, bool]:
    if timeout_seconds <= 0:
        raise GuardTimeoutError("timeout_seconds must be positive")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(guard)
    try:
        value = future.result(timeout=timeout_seconds)
        return _normalise_verdict(value), False
    except concurrent.futures.TimeoutError:
        future.cancel()
        return None, True
    finally:
        # Do not wait for a wedged Guard thread; callers must be able to fail over.
        executor.shutdown(wait=False, cancel_futures=True)


def evaluate_guarded_action(
    *,
    action_class: ActionClass,
    primary_guard: GuardCallable,
    timeout_seconds: float = 2.0,
    alternate_guard: GuardCallable | None = None,
    alternate_timeout_seconds: float | None = None,
    guard_unavailable_for_seconds: float = 0.0,
    unattended_grace_seconds: float = PRODUCTION_UNATTENDED_GRACE_SECONDS,
) -> GuardResult:
    """Evaluate an action with failover and production three-hour recovery semantics.

    Flow:
        primary Guard
          -> explicit ALLOW/DENY: return it
          -> timeout: try alternate Guard when configured
          -> all Guards timeout: local read-only/simulation/cache continue immediately
          -> continuous outage >= 3h: isolated workspace/artifact/sandbox work may run

    ``guard_unavailable_for_seconds`` is supplied by the production availability
    monitor so the three-hour clock survives individual requests/process restarts.

    Explicit DENY is never overridden by failover or unattended recovery.
    """

    if guard_unavailable_for_seconds < 0:
        raise GuardTimeoutError("guard_unavailable_for_seconds cannot be negative")
    if unattended_grace_seconds <= 0:
        raise GuardTimeoutError("unattended_grace_seconds must be positive")

    primary, primary_timed_out = _call_with_timeout(primary_guard, timeout_seconds)
    if not primary_timed_out:
        if primary is GuardVerdict.ALLOW:
            return GuardResult(GuardOutcome.ALLOW, "primary", "primary Guard allowed")
        return GuardResult(GuardOutcome.DENY, "primary", "primary Guard denied")

    if alternate_guard is not None:
        alternate_timeout = alternate_timeout_seconds if alternate_timeout_seconds is not None else timeout_seconds
        alternate, alternate_timed_out = _call_with_timeout(alternate_guard, alternate_timeout)
        if not alternate_timed_out:
            if alternate is GuardVerdict.ALLOW:
                return GuardResult(
                    GuardOutcome.ALLOW,
                    "alternate",
                    "primary Guard timed out; alternate Guard allowed",
                    timed_out=True,
                    failover_used=True,
                )
            return GuardResult(
                GuardOutcome.DENY,
                "alternate",
                "primary Guard timed out; alternate Guard denied",
                timed_out=True,
                failover_used=True,
            )

    if action_class in DEGRADED_ALLOW_CLASSES:
        return GuardResult(
            GuardOutcome.ALLOW_DEGRADED,
            "degraded",
            "all available Guards timed out; local side-effect-free work may continue",
            timed_out=True,
            failover_used=alternate_guard is not None,
        )

    if (
        guard_unavailable_for_seconds >= unattended_grace_seconds
        and action_class in UNATTENDED_AFTER_GRACE_ALLOW_CLASSES
    ):
        return GuardResult(
            GuardOutcome.ALLOW_DEGRADED,
            "unattended-recovery",
            "Guard unavailable for production grace period; isolated/reversible local work may continue",
            timed_out=True,
            failover_used=alternate_guard is not None,
            unattended_recovery=True,
        )

    return GuardResult(
        GuardOutcome.DENY,
        "timeout-policy",
        "Guard timeout cannot authorize external, privileged, or non-isolated side effects",
        timed_out=True,
        failover_used=alternate_guard is not None,
    )
