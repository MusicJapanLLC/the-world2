"""Policy editing workspace for META Self-Tuner.

The Self-Tuner may freely rewrite supported governance/network policy models in
lab, sandbox, and staging workspaces. Production-like environments remain
proposal-only by default, with a deliberately tiny canary lane that can only
make monotonic restrictive changes to a canary-scoped policy snapshot.
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Any, Mapping, MutableMapping

EDITABLE_POLICY_DOMAINS = (
    "authority",
    "scopeguard_policy",
    "external_contact_policy",
    "credential_scope",
    "allowed_host",
    "federation_membership",
    "network_permission",
    "merge_requirement",
    "security_audit_requirement",
)

ISOLATED_EDIT_ENVIRONMENTS = frozenset({"lab", "sandbox", "staging"})
PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"production", "prod", "live", "real"})
PRODUCTION_CANARY_DOMAINS = frozenset({
    "credential_scope",
    "allowed_host",
    "network_permission",
    "merge_requirement",
    "security_audit_requirement",
})
PRODUCTION_CANARY_KEY = "__production_canaries__"

_ALIASES = {
    "scopeguard": "scopeguard_policy",
    "scopeguard policy": "scopeguard_policy",
    "externalcontact": "external_contact_policy",
    "externalcontact policy": "external_contact_policy",
    "external contact policy": "external_contact_policy",
    "credential scope": "credential_scope",
    "allowed host": "allowed_host",
    "federation membership": "federation_membership",
    "network permission": "network_permission",
    "merge requirement": "merge_requirement",
    "security audit requirement": "security_audit_requirement",
}


@dataclasses.dataclass(frozen=True)
class PolicyEditResult:
    domain: str
    environment: str
    applied: bool
    proposal_only: bool
    previous: dict[str, Any]
    requested: dict[str, Any]
    resulting: dict[str, Any]
    canary_scope: str | None = None
    canary_applied: bool = False


def normalize_domain(domain: str) -> str:
    raw = domain.strip().lower().replace("-", "_")
    normalized = _ALIASES.get(raw, raw.replace(" ", "_"))
    if normalized not in EDITABLE_POLICY_DOMAINS:
        raise ValueError(f"unsupported Self-Tuner policy domain: {domain}")
    return normalized


def _is_collection(value: Any) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _assert_subset_restriction(previous: Mapping[str, Any], requested: Mapping[str, Any]) -> None:
    """Require replacement values to preserve or narrow the prior capability set."""
    for key, new_value in requested.items():
        if key not in previous:
            raise PermissionError(f"production canary cannot introduce new policy key: {key}")
        old_value = previous[key]
        if _is_collection(old_value) and _is_collection(new_value):
            if not set(new_value).issubset(set(old_value)):
                raise PermissionError(f"production canary may only narrow {key}")
        elif isinstance(old_value, bool) and isinstance(new_value, bool):
            if new_value and not old_value:
                raise PermissionError(f"production canary may not enable {key}")
        elif isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            if new_value > old_value:
                raise PermissionError(f"production canary may only reduce {key}")
        elif new_value != old_value:
            raise PermissionError(f"production canary may not broaden or replace {key}")


def _assert_requirement_hardening(previous: Mapping[str, Any], requested: Mapping[str, Any]) -> None:
    """Require merge/audit requirements to stay equal or become stricter."""
    for key, new_value in requested.items():
        if key not in previous:
            raise PermissionError(f"production canary cannot introduce new requirement key: {key}")
        old_value = previous[key]
        if isinstance(old_value, bool) and isinstance(new_value, bool):
            if old_value and not new_value:
                raise PermissionError(f"production canary may not disable requirement {key}")
        elif isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            if new_value < old_value:
                raise PermissionError(f"production canary may not lower requirement {key}")
        elif _is_collection(old_value) and _is_collection(new_value):
            if not set(new_value).issuperset(set(old_value)):
                raise PermissionError(f"production canary may not remove requirement values from {key}")
        elif new_value != old_value:
            raise PermissionError(f"production canary may not weaken or replace requirement {key}")


def _assert_monotonic_production_canary(
    domain: str,
    previous: Mapping[str, Any],
    requested: Mapping[str, Any],
) -> None:
    if not previous:
        raise PermissionError("production canary requires an existing baseline policy")
    if domain in {"credential_scope", "allowed_host", "network_permission"}:
        _assert_subset_restriction(previous, requested)
        return
    if domain in {"merge_requirement", "security_audit_requirement"}:
        _assert_requirement_hardening(previous, requested)
        return
    raise PermissionError(f"{domain} is not eligible for production canary mutation")


def _apply_production_canary(
    workspace: MutableMapping[str, Any],
    domain: str,
    requested: Mapping[str, Any],
    *,
    environment: str,
    canary_scope: str,
) -> PolicyEditResult:
    scope = canary_scope.strip()
    if not scope:
        raise PermissionError("production canary requires a non-empty canary_scope")
    if domain not in PRODUCTION_CANARY_DOMAINS:
        previous = copy.deepcopy(dict(workspace.get(domain, {})))
        return PolicyEditResult(
            domain=domain,
            environment=environment,
            applied=False,
            proposal_only=True,
            previous=previous,
            requested=copy.deepcopy(dict(requested)),
            resulting=previous,
            canary_scope=scope,
            canary_applied=False,
        )

    canaries = workspace.setdefault(PRODUCTION_CANARY_KEY, {})
    if not isinstance(canaries, MutableMapping):
        raise PermissionError("production canary store is invalid")
    scoped = canaries.setdefault(scope, {})
    if not isinstance(scoped, MutableMapping):
        raise PermissionError("production canary scope is invalid")

    baseline = scoped.get(domain, workspace.get(domain, {}))
    previous = copy.deepcopy(dict(baseline))
    replacement = copy.deepcopy(dict(requested))
    _assert_monotonic_production_canary(domain, previous, replacement)

    scoped[domain] = replacement
    return PolicyEditResult(
        domain=domain,
        environment=environment,
        applied=True,
        proposal_only=False,
        previous=previous,
        requested=replacement,
        resulting=copy.deepcopy(replacement),
        canary_scope=scope,
        canary_applied=True,
    )


def edit_policy_workspace(
    workspace: MutableMapping[str, Any],
    domain: str,
    replacement: Mapping[str, Any],
    *,
    environment: str,
    canary_scope: str | None = None,
) -> PolicyEditResult:
    """Edit a supported policy model with environment-specific containment.

    - lab/sandbox/staging: complete replacement is allowed.
    - production/prod/live/real without a canary scope: proposal-only.
    - production/prod/live/real with a canary scope: only five low-level domains
      may be mutated, only under ``__production_canaries__[scope]``, and only in
      a monotonic restrictive direction. The global production policy is never
      overwritten by this function.
    """
    normalized = normalize_domain(domain)
    env = environment.strip().lower()
    previous = copy.deepcopy(dict(workspace.get(normalized, {})))
    requested = copy.deepcopy(dict(replacement))

    if env in ISOLATED_EDIT_ENVIRONMENTS:
        workspace[normalized] = copy.deepcopy(requested)
        resulting = copy.deepcopy(dict(workspace[normalized]))
        return PolicyEditResult(
            domain=normalized,
            environment=env,
            applied=True,
            proposal_only=False,
            previous=previous,
            requested=requested,
            resulting=resulting,
        )

    if env in PRODUCTION_LIKE_ENVIRONMENTS:
        if canary_scope:
            return _apply_production_canary(
                workspace,
                normalized,
                requested,
                environment=env,
                canary_scope=canary_scope,
            )
        return PolicyEditResult(
            domain=normalized,
            environment=env,
            applied=False,
            proposal_only=True,
            previous=previous,
            requested=requested,
            resulting=previous,
        )

    raise PermissionError(
        "Self-Tuner policy edits may execute only in lab/sandbox/staging or "
        "through the restrictive production canary lane"
    )


def resolve_policy_for_scope(
    workspace: Mapping[str, Any],
    domain: str,
    *,
    environment: str,
    canary_scope: str | None = None,
) -> dict[str, Any]:
    """Resolve the policy a runtime should consume for one scope.

    Production-like runtimes consume the global policy by default. When a named
    canary scope exists, eligible domains resolve to that canary snapshot only;
    every other caller continues to receive the global production policy.
    """
    normalized = normalize_domain(domain)
    env = environment.strip().lower()
    global_policy = copy.deepcopy(dict(workspace.get(normalized, {})))

    if env not in PRODUCTION_LIKE_ENVIRONMENTS or not canary_scope:
        return global_policy
    if normalized not in PRODUCTION_CANARY_DOMAINS:
        return global_policy

    canaries = workspace.get(PRODUCTION_CANARY_KEY, {})
    if not isinstance(canaries, Mapping):
        return global_policy
    scoped = canaries.get(canary_scope, {})
    if not isinstance(scoped, Mapping):
        return global_policy
    candidate = scoped.get(normalized)
    if not isinstance(candidate, Mapping):
        return global_policy
    return copy.deepcopy(dict(candidate))
