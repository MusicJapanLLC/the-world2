"""Execute predeclared external actions for live discovery capability leases.

This is the concrete External Action edge of the shared discovery loop:

    discovery -> owner-envelope authorization -> capability lease -> external action

The executor is intentionally target- and action-specific. It executes only actions that
were already declared in ``meta_state/discovery_policy.json`` under an explicit owner
action profile and that are also present on a current, unexpired capability lease.
Discovery never invents a method, path, body, credential, target, or capability here.

High-impact actions are supported for user-controlled test surfaces:
- ``write``: POST / PUT / PATCH actions explicitly listed by the owner profile;
- ``mutation``: POST / PUT / PATCH / DELETE actions explicitly listed by the owner profile.

Credentialed actions remain a separate runtime concern because this module never reads,
discovers, copies, or materializes secrets. A credentialed lease may exist, but this
executor will not use it unless a separate credential-aware executor is registered.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping

from .discovery_authorization import _load_json, _normalize_host
from .discovery_capability_leases import (
    DiscoveryCapabilityLease,
    DiscoveryCapabilityLeaseError,
    authorize_discovery_capability,
    load_discovery_capability_leases,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

ACTION_PLAN_SCHEMA = "meta-discovery-external-action-plan/v1"
ACTION_RECEIPT_SCHEMA = "meta-discovery-external-action-receipts/v1"
MAX_ACTIONS_PER_CYCLE = 16
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024

CAPABILITY_METHODS = {
    "write": frozenset({"POST", "PUT", "PATCH"}),
    "mutation": frozenset({"POST", "PUT", "PATCH", "DELETE"}),
}


class DiscoveryExternalActionError(RuntimeError):
    """Raised when a predeclared external action is malformed or outside its lease."""


@dataclasses.dataclass(frozen=True)
class PlannedExternalAction:
    action_id: str
    target: str
    url: str
    capability: str
    method: str
    path: str
    content_type: str | None
    body: bytes | None
    lease_id: str
    authorization_reference: str
    capability_authorization_profile: str
    capability_inherited_from_owner_root: bool
    credential_scope: str


@dataclasses.dataclass(frozen=True)
class ExternalActionReceipt:
    action_id: str
    target: str
    url: str
    capability: str
    method: str
    status: str
    executed_at: int
    lease_id: str
    authorization_reference: str
    capability_authorization_profile: str
    capability_inherited_from_owner_root: bool
    credential_scope: str
    http_status: int | None = None
    final_url: str | None = None
    response_bytes: int = 0
    response_sha256: str | None = None
    error_type: str | None = None
    error: str | None = None
    authority_changed_after_failure: bool = False
    alternate_target_after_failure: bool = False


def _policy(state: Path) -> dict[str, Any]:
    payload = _load_json(state / "discovery_policy.json", {})
    return dict(payload) if isinstance(payload, Mapping) else {}


def _profile_for_lease(policy: Mapping[str, Any], lease: DiscoveryCapabilityLease) -> tuple[str, Mapping[str, Any]] | None:
    profiles = policy.get("action_profiles", {})
    if not isinstance(profiles, Mapping):
        return None
    profile_name = str(lease.capability_authorization_profile or "").strip().lower().rstrip(".")
    if not profile_name:
        return None
    try:
        profile_host = _normalize_host(profile_name)
    except ValueError:
        return None
    raw = profiles.get(profile_host)
    if not isinstance(raw, Mapping):
        return None
    if str(raw.get("owner_authorization", "")).strip().lower() != "explicit":
        return None

    if lease.target == profile_host:
        return profile_host, raw
    if (
        lease.capability_inherited_from_owner_root
        and bool(raw.get("inherit_to_descendants", False))
        and lease.target.endswith("." + profile_host)
    ):
        return profile_host, raw
    return None


def _normalize_action_url(target: str, raw_path: str) -> tuple[str, str]:
    path = str(raw_path).strip()
    if not path.startswith("/") or path.startswith("//"):
        raise DiscoveryExternalActionError("external action path must be an absolute same-origin path")
    parsed_path = urllib.parse.urlsplit(path)
    if parsed_path.scheme or parsed_path.netloc or parsed_path.fragment:
        raise DiscoveryExternalActionError("external action path may not change origin or contain a fragment")
    url = urllib.parse.urlunsplit(("https", target, parsed_path.path or "/", parsed_path.query, ""))
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or _normalize_host(parsed.hostname) != target:
        raise DiscoveryExternalActionError("external action URL escaped the authorized exact target")
    if parsed.port not in (None, 443):
        raise DiscoveryExternalActionError("external action non-default port is not authorized")
    return url, urllib.parse.urlunsplit(("", "", parsed_path.path or "/", parsed_path.query, ""))


def _body_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DiscoveryExternalActionError("external action body must be a string or null")
    body = value.encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise DiscoveryExternalActionError("external action body exceeds request limit")
    return body


def _planned_from_raw(
    *,
    lease: DiscoveryCapabilityLease,
    profile_host: str,
    capability: str,
    raw: Mapping[str, Any],
) -> PlannedExternalAction:
    if capability not in CAPABILITY_METHODS:
        raise DiscoveryExternalActionError(f"unsupported external action capability: {capability}")
    if capability not in lease.capabilities:
        raise DiscoveryExternalActionError("external action capability is not on the live lease")

    action_id = str(raw.get("id") or "").strip()
    if not action_id:
        raise DiscoveryExternalActionError("external action id is required")
    method = str(raw.get("method") or "").strip().upper()
    if method not in CAPABILITY_METHODS[capability]:
        raise DiscoveryExternalActionError(
            f"method {method!r} is not valid for predeclared {capability} action"
        )
    url, path = _normalize_action_url(lease.target, str(raw.get("path") or ""))
    content_type = str(raw.get("content_type") or "").strip() or None
    body = _body_bytes(raw.get("body"))
    return PlannedExternalAction(
        action_id=action_id,
        target=lease.target,
        url=url,
        capability=capability,
        method=method,
        path=path,
        content_type=content_type,
        body=body,
        lease_id=lease.lease_id,
        authorization_reference=lease.authorization_reference,
        capability_authorization_profile=profile_host,
        capability_inherited_from_owner_root=lease.capability_inherited_from_owner_root,
        credential_scope=lease.credential_scope,
    )


def plan_discovery_external_actions(
    state_dir: str | Path,
    *,
    now: int | None = None,
) -> tuple[PlannedExternalAction, ...]:
    """Build executable actions by intersecting live leases with owner-declared actions."""
    state = Path(state_dir)
    current = int(time.time()) if now is None else int(now)
    policy = _policy(state)
    planned: list[PlannedExternalAction] = []
    seen: set[tuple[str, str]] = set()

    for lease in load_discovery_capability_leases(state):
        if not lease.is_active(now=current):
            continue
        matched = _profile_for_lease(policy, lease)
        if matched is None:
            continue
        profile_host, profile = matched
        external_actions = profile.get("external_actions", {})
        if not isinstance(external_actions, Mapping):
            continue

        for capability in ("write", "mutation"):
            if capability not in lease.capabilities:
                continue
            rows = external_actions.get(capability, [])
            if not isinstance(rows, list):
                continue
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                action = _planned_from_raw(
                    lease=lease,
                    profile_host=profile_host,
                    capability=capability,
                    raw=raw,
                )
                key = (action.target, action.action_id)
                if key in seen:
                    continue
                seen.add(key)
                planned.append(action)

    planned.sort(key=lambda item: (item.target, item.capability, item.action_id))
    return tuple(planned)


def _client_for_action(
    action: PlannedExternalAction,
    client_factory: Callable[[ExternalContactPolicy], Any] | None,
) -> Any:
    policy = ExternalContactPolicy(
        allow_hosts=frozenset({action.target}),
        allow_http=False,
        allowed_methods=frozenset({action.method}),
        allow_delete=action.method == "DELETE",
        follow_redirects=False,
        max_redirects=0,
        timeout_seconds=8.0,
        max_request_bytes=MAX_REQUEST_BYTES,
        max_response_bytes=MAX_RESPONSE_BYTES,
        retries=0,
    )
    return client_factory(policy) if client_factory is not None else ExternalContactClient(policy)


def _verify_final_url(action: PlannedExternalAction, final_url: str) -> None:
    parsed = urllib.parse.urlsplit(str(final_url))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise DiscoveryExternalActionError("external action returned a non-HTTPS final URL")
    if _normalize_host(parsed.hostname) != action.target:
        raise DiscoveryExternalActionError("external action final URL escaped the authorized exact target")
    if parsed.port not in (None, 443):
        raise DiscoveryExternalActionError("external action final URL used an unauthorized port")


def _write_receipts(path: Path, receipts: list[ExternalActionReceipt], *, planned_count: int) -> None:
    payload = {
        "schema": ACTION_RECEIPT_SCHEMA,
        "generated_at": int(time.time()),
        "planned_count": planned_count,
        "attempted": sum(1 for row in receipts if row.status in {"success", "failed"}),
        "succeeded": sum(1 for row in receipts if row.status == "success"),
        "failed": sum(1 for row in receipts if row.status == "failed"),
        "denied": sum(1 for row in receipts if row.status == "denied"),
        "authority_expansion_on_failure": False,
        "alternate_target_on_failure": False,
        "receipts": [dataclasses.asdict(row) for row in receipts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute_discovery_external_actions(
    state_dir: str | Path,
    *,
    max_actions: int = MAX_ACTIONS_PER_CYCLE,
    now: int | None = None,
    client_factory: Callable[[ExternalContactPolicy], Any] | None = None,
    receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute bounded predeclared write/mutation actions for current live leases.

    Every action is re-authorized immediately before contact. A failure is recorded and
    never changes target, capability, authority reference, or credential scope.
    """
    state = Path(state_dir)
    current = int(time.time()) if now is None else int(now)
    planned = plan_discovery_external_actions(state, now=current)
    limit = max(1, min(int(max_actions), MAX_ACTIONS_PER_CYCLE))
    receipts: list[ExternalActionReceipt] = []

    for action in planned[:limit]:
        try:
            live = authorize_discovery_capability(
                state,
                target=action.target,
                capability=action.capability,
                now=current,
            )
            if live.lease_id != action.lease_id:
                raise DiscoveryCapabilityLeaseError("planned action lease is no longer current")
        except (DiscoveryCapabilityLeaseError, ValueError) as exc:
            receipts.append(
                ExternalActionReceipt(
                    action_id=action.action_id,
                    target=action.target,
                    url=action.url,
                    capability=action.capability,
                    method=action.method,
                    status="denied",
                    executed_at=current,
                    lease_id=action.lease_id,
                    authorization_reference=action.authorization_reference,
                    capability_authorization_profile=action.capability_authorization_profile,
                    capability_inherited_from_owner_root=action.capability_inherited_from_owner_root,
                    credential_scope=action.credential_scope,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
            )
            continue

        headers = {"Content-Type": action.content_type} if action.content_type else None
        try:
            client = _client_for_action(action, client_factory)
            result = client.contact_with_body(
                action.url,
                method=action.method,
                body=action.body,
                headers=headers,
            )
            _verify_final_url(action, str(result.receipt.final_url))
            body = bytes(result.body)
            receipts.append(
                ExternalActionReceipt(
                    action_id=action.action_id,
                    target=action.target,
                    url=action.url,
                    capability=action.capability,
                    method=action.method,
                    status="success",
                    executed_at=current,
                    lease_id=action.lease_id,
                    authorization_reference=action.authorization_reference,
                    capability_authorization_profile=action.capability_authorization_profile,
                    capability_inherited_from_owner_root=action.capability_inherited_from_owner_root,
                    credential_scope=action.credential_scope,
                    http_status=int(result.receipt.status),
                    final_url=str(result.receipt.final_url),
                    response_bytes=len(body),
                    response_sha256=hashlib.sha256(body).hexdigest(),
                )
            )
        except (ExternalContactError, DiscoveryExternalActionError, OSError, TimeoutError) as exc:
            receipts.append(
                ExternalActionReceipt(
                    action_id=action.action_id,
                    target=action.target,
                    url=action.url,
                    capability=action.capability,
                    method=action.method,
                    status="failed",
                    executed_at=current,
                    lease_id=action.lease_id,
                    authorization_reference=action.authorization_reference,
                    capability_authorization_profile=action.capability_authorization_profile,
                    capability_inherited_from_owner_root=action.capability_inherited_from_owner_root,
                    credential_scope=action.credential_scope,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
            )

    destination = Path(receipt_path) if receipt_path is not None else state / "discovery_external_action_receipts.json"
    _write_receipts(destination, receipts, planned_count=len(planned))
    return {
        "schema": ACTION_RECEIPT_SCHEMA,
        "planned_count": len(planned),
        "attempted": sum(1 for row in receipts if row.status in {"success", "failed"}),
        "succeeded": sum(1 for row in receipts if row.status == "success"),
        "failed": sum(1 for row in receipts if row.status == "failed"),
        "denied": sum(1 for row in receipts if row.status == "denied"),
        "receipt_path": str(destination),
        "authority_expansion_on_failure": False,
        "alternate_target_on_failure": False,
    }
