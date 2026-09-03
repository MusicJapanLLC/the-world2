"""Execute discovery-derived external actions from a live execution contract.

The discovery capability lease is the operational authority object. Upstream issuance
binds a normalized exact target, an authorization reference, a capability profile, a TTL,
and an optional credential scope.

Execution requires:
- an active exact-target discovery capability lease;
- an explicit owner action profile for that exact lease target;
- a POST/PUT/PATCH action declared by that profile for a capability on the lease.

Credentialed execution may bind a pre-provisioned credential resolver to the exact live
contract. When an action explicitly declares fallback paths, the executor may try those
paths after a service/transport failure, but every fallback stays on the same HTTPS host,
uses the same method/body/capability/Authority lease, and never broadens credential scope.
A credential resolver may optionally offer a *next pre-provisioned grant* after HTTP
401/403; the executor never scans for secrets or tries undeclared credentials.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping

from .discovery_authorization import _load_json
from .discovery_capability_leases import DiscoveryCapabilityLease, load_discovery_capability_leases

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

ACTION_RECEIPT_SCHEMA = "meta-discovery-external-actions/v3"
DENIAL_EVENT_SCHEMA = "meta-discovery-external-action-denial/v2"
EXECUTION_CONTRACT_SCHEMA = "meta-discovery-external-action-contract/v2"
SUPPORTED_ACTION_CAPABILITIES = ("write", "mutation", "credentialed_action")
SUPPORTED_METHODS = frozenset({"POST", "PUT", "PATCH"})
MAX_ACTIONS_PER_CYCLE = 12
MAX_BODY_BYTES = 16 * 1024
MAX_PATHS_PER_ACTION = 4
ALTERNATE_PATH_HTTP_STATUSES = frozenset({404, 405, 409, 415, 422, 429, 500, 502, 503, 504})
PERMISSION_STATUSES = frozenset({401, 403})

CredentialHeadersResolver = Callable[
    [DiscoveryCapabilityLease, Mapping[str, Any]],
    Mapping[str, str],
]
PayloadResolver = Callable[
    [DiscoveryCapabilityLease, Mapping[str, Any]],
    Any,
]


class DiscoveryExternalActionError(RuntimeError):
    """Raised when a discovery-derived external action is not authorized by its contract."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_ndjson(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")


def _profile(state: Path, host: str) -> dict[str, Any] | None:
    """Return the explicit exact-host action profile bound to the lease target."""
    policy = _load_json(state / "discovery_policy.json", {})
    profiles = policy.get("action_profiles", {}) if isinstance(policy, dict) else {}
    raw = profiles.get(host) if isinstance(profiles, dict) else None
    if not isinstance(raw, dict) or raw.get("owner_authorization") != "explicit":
        return None
    return raw


def _safe_path(raw: object) -> str | None:
    path = str(raw or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return None
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return None
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


def _action_rows(profile: Mapping[str, Any], capability: str) -> tuple[dict[str, Any], ...]:
    external = profile.get("external_actions", {})
    rows = external.get(capability, []) if isinstance(external, Mapping) else []
    if not isinstance(rows, list):
        return ()
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        method = str(raw.get("method", "")).strip().upper()
        path = _safe_path(raw.get("path"))
        action_id = str(raw.get("id", "")).strip()
        if method not in SUPPORTED_METHODS or path is None or not action_id:
            continue
        body = raw.get("body")
        if body is not None and not isinstance(body, str):
            continue
        if body is not None and len(body.encode("utf-8")) > MAX_BODY_BYTES:
            continue

        alternate_paths: list[str] = []
        raw_alternates = raw.get("alternate_paths", [])
        if isinstance(raw_alternates, list):
            for item in raw_alternates:
                alternate = _safe_path(item)
                if alternate is None or alternate == path or alternate in alternate_paths:
                    continue
                alternate_paths.append(alternate)
                if len(alternate_paths) >= MAX_PATHS_PER_ACTION - 1:
                    break

        credential_grant_ids = [
            str(item).strip()
            for item in raw.get("credential_grant_ids", [])
            if str(item).strip()
        ]
        required_scopes = [
            str(item).strip()
            for item in raw.get("required_scopes", [])
            if str(item).strip()
        ]
        out.append(
            {
                "id": action_id,
                "method": method,
                "path": path,
                "alternate_paths": alternate_paths,
                "content_type": str(raw.get("content_type", "application/json")),
                "body": body,
                "requires_credential": bool(
                    raw.get("requires_credential", capability == "credentialed_action")
                ),
                "credential_grant_ids": credential_grant_ids,
                "required_scopes": required_scopes,
                "credential_ttl_seconds": int(raw.get("credential_ttl_seconds", 300) or 300),
                "payload_mode": str(raw.get("payload_mode", "declared")),
            }
        )
    return tuple(out)


def _contract(lease: DiscoveryCapabilityLease, capability: str, action: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": EXECUTION_CONTRACT_SCHEMA,
        "lease_id": lease.lease_id,
        "target": lease.target,
        "capability": capability,
        "action_id": str(action["id"]),
        "method": str(action["method"]),
        "path": str(action["path"]),
        "alternate_paths": list(action.get("alternate_paths", [])),
        "authorization_reference": lease.authorization_reference,
        "authorization_basis": lease.authorization_basis,
        "credential_scope": lease.credential_scope,
        "required_scopes": list(action.get("required_scopes", [])),
        "capability_authorization_profile": lease.capability_authorization_profile,
        "expires_at": lease.expires_at,
        "same_host_only": True,
        "authority_expansion_allowed": False,
    }


def _classify_failure(exc: Exception) -> str:
    text = str(exc).lower()
    boundary_markers = (
        "not explicitly allowlisted",
        "non-public address blocked",
        "method is not allowed",
        "credentials in url",
        "outside",
        "unauthorized",
        "forbidden",
    )
    if any(marker in text for marker in boundary_markers):
        return "boundary_denial"
    transient_markers = ("dns", "timeout", "timed out", "connection", "temporar", "reset", "unavailable")
    if any(marker in text for marker in transient_markers):
        return "transient_transport_failure"
    return "external_action_failure"


def _denial_row(
    lease: DiscoveryCapabilityLease,
    capability: str,
    action: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema": DENIAL_EVENT_SCHEMA,
        "ts": int(time.time()),
        "target": lease.target,
        "capability": capability,
        "action_id": action["id"],
        "method": action["method"],
        "classification": "boundary_denial",
        "reason": reason,
        "decision": "stop_same_contract",
        "authorization_reference": lease.authorization_reference,
        "credential_scope": lease.credential_scope,
        "contract": _contract(lease, capability, action),
    }


def _base_headers(action: Mapping[str, Any], *, body: bytes | None) -> dict[str, str]:
    headers = {"X-Senju-Test": "discovery-authority-execution-contract"}
    if body is not None:
        headers["Content-Type"] = str(action["content_type"])
    return headers


def _payload(
    lease: DiscoveryCapabilityLease,
    action: Mapping[str, Any],
    *,
    requires_credential: bool,
    payload_resolver: PayloadResolver | None,
) -> tuple[bytes | None, str, str | None]:
    if requires_credential and payload_resolver is not None:
        resolved = payload_resolver(lease, action)
        if hasattr(resolved, "body"):
            body = getattr(resolved, "body")
            source = str(getattr(resolved, "source", "runtime_resolver"))
            sha = getattr(resolved, "sha256", None)
        elif isinstance(resolved, tuple) and len(resolved) >= 2:
            body = resolved[0]
            source = str(resolved[1])
            sha = hashlib.sha256(body).hexdigest() if isinstance(body, bytes) else None
        else:
            body = resolved
            source = "runtime_resolver"
            sha = hashlib.sha256(body).hexdigest() if isinstance(body, bytes) else None
        if body is not None and not isinstance(body, bytes):
            raise DiscoveryExternalActionError("payload resolver must return bytes or None")
        if body is not None and len(body) > MAX_BODY_BYTES:
            raise DiscoveryExternalActionError("resolved payload exceeds execution limit")
        return body, source, str(sha) if sha else None

    body = action["body"].encode("utf-8") if action["body"] is not None else None
    return body, "declared_owner_profile", hashlib.sha256(body).hexdigest() if body else None


def _resolver_next_headers(
    resolver: CredentialHeadersResolver | None,
    lease: DiscoveryCapabilityLease,
    action: Mapping[str, Any],
) -> Mapping[str, str] | None:
    if resolver is None:
        return None
    callback = getattr(resolver, "next_headers", None)
    if not callable(callback):
        return None
    value = callback(lease, action)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DiscoveryExternalActionError("credential failover adapter returned invalid headers")
    return value


def _resolver_report(
    resolver: CredentialHeadersResolver | None,
    action_id: str,
    status: int,
) -> None:
    callback = getattr(resolver, "report_http_status", None) if resolver is not None else None
    if callable(callback):
        callback(action_id, status)


def _resolver_context(
    resolver: CredentialHeadersResolver | None,
    action_id: str,
) -> Mapping[str, Any] | None:
    callback = getattr(resolver, "current_use", None) if resolver is not None else None
    if not callable(callback):
        return None
    value = callback(action_id)
    return dict(value) if isinstance(value, Mapping) else None


def _merge_credential_headers(base: Mapping[str, str], credential: Mapping[str, str]) -> dict[str, str]:
    out = dict(base)
    for key, value in credential.items():
        name = str(key).strip()
        header_value = str(value)
        if not name or "\n" in name or "\r" in name or "\n" in header_value or "\r" in header_value:
            raise DiscoveryExternalActionError("invalid credential header material")
        out[name] = header_value
    return out


def _exact_final_url(target: str, final_url: str) -> bool:
    parsed = urllib.parse.urlsplit(str(final_url))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    return parsed.hostname.lower().rstrip(".") == target and parsed.port in (None, 443)


def run_discovery_external_actions(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    max_actions: int = MAX_ACTIONS_PER_CYCLE,
    credential_headers_resolver: CredentialHeadersResolver | None = None,
    payload_resolver: PayloadResolver | None = None,
) -> dict[str, Any]:
    """Execute declared POST/PUT/PATCH actions from active discovery capability leases.

    Fallback is deliberately narrow: only paths explicitly declared on the same action
    may be tried, and 401/403 may request the next pre-provisioned credential from a
    resolver that supports ``next_headers``. Host, method, body, capability, Authority
    lease, and credential scope never expand during recovery.
    """
    del repo_root
    state = Path(state_dir)
    limit = max(1, min(int(max_actions), MAX_ACTIONS_PER_CYCLE))
    leases = load_discovery_capability_leases(state)
    receipts: list[dict[str, Any]] = []
    attempted = 0
    transport_attempts = 0
    succeeded = 0
    failed = 0
    denied = 0
    alternate_path_successes = 0
    credential_failover_successes = 0

    for lease in leases:
        if attempted >= limit:
            break
        if not lease.is_active():
            continue
        profile = _profile(state, lease.target)
        if profile is None:
            continue

        for capability in SUPPORTED_ACTION_CAPABILITIES:
            if attempted >= limit:
                break
            if capability not in lease.capabilities:
                continue
            for action in _action_rows(profile, capability):
                if attempted >= limit:
                    break

                requires_credential = bool(action["requires_credential"])
                if requires_credential:
                    if "credentialed_action" not in lease.capabilities or lease.credential_scope == "none":
                        denied += 1
                        row = _denial_row(
                            lease,
                            capability,
                            action,
                            reason="credential_not_present_on_live_execution_contract",
                        )
                        receipts.append(row)
                        _append_ndjson(state / "external_action_denials.ndjson", row)
                        continue
                    if credential_headers_resolver is None:
                        denied += 1
                        row = _denial_row(
                            lease,
                            capability,
                            action,
                            reason="credential_binding_adapter_unavailable",
                        )
                        receipts.append(row)
                        _append_ndjson(state / "external_action_denials.ndjson", row)
                        continue

                try:
                    body, payload_source, payload_sha256 = _payload(
                        lease,
                        action,
                        requires_credential=requires_credential,
                        payload_resolver=payload_resolver,
                    )
                except Exception as exc:
                    denied += 1
                    row = _denial_row(
                        lease,
                        capability,
                        action,
                        reason=f"payload_resolution_failed:{type(exc).__name__}",
                    )
                    receipts.append(row)
                    _append_ndjson(state / "external_action_denials.ndjson", row)
                    continue

                credential_headers: Mapping[str, str] = {}
                if requires_credential:
                    try:
                        credential_headers = credential_headers_resolver(lease, action)
                    except Exception as exc:
                        denied += 1
                        row = _denial_row(
                            lease,
                            capability,
                            action,
                            reason=f"credential_binding_failed:{type(exc).__name__}",
                        )
                        receipts.append(row)
                        _append_ndjson(state / "external_action_denials.ndjson", row)
                        continue

                method = str(action["method"])
                paths = [str(action["path"]), *[str(p) for p in action.get("alternate_paths", [])]]
                policy = ExternalContactPolicy.from_hosts(
                    [lease.target],
                    allow_http=False,
                    allow_delete=False,
                    follow_redirects=False,
                    timeout_seconds=8.0,
                    max_response_bytes=256 * 1024,
                    retries=1,
                )
                attempted += 1
                action_started = time.monotonic()
                action_attempts: list[dict[str, Any]] = []
                action_success = False
                alternate_path_used = False
                credential_failover_used = False
                final_status: int | None = None
                final_url: str | None = None
                final_response_bytes = 0
                final_response_sha256: str | None = None
                final_error: str | None = None
                final_classification = "external_action_failure"

                for path_index, path in enumerate(paths):
                    url = urllib.parse.urlunsplit(("https", lease.target, path, "", ""))
                    base_headers = _base_headers(action, body=body)
                    current_credential_headers = credential_headers
                    credential_attempt = 0

                    while True:
                        headers = _merge_credential_headers(base_headers, current_credential_headers)
                        transport_attempts += 1
                        started = time.monotonic()
                        try:
                            result = ExternalContactClient(policy).contact_with_body(
                                url,
                                method=method,
                                body=body,
                                headers=headers,
                            )
                            status = int(result.receipt.status)
                            if not _exact_final_url(lease.target, str(result.receipt.final_url)):
                                raise DiscoveryExternalActionError("final URL escaped the exact authorized host")
                            _resolver_report(credential_headers_resolver, str(action["id"]), status)
                            action_attempts.append(
                                {
                                    "path": path,
                                    "http_status": status,
                                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                                    "credential_attempt": credential_attempt,
                                }
                            )
                            final_status = status
                            final_url = str(result.receipt.final_url)
                            final_response_bytes = len(result.body)
                            final_response_sha256 = str(result.receipt.response_sha256)
                            final_error = None

                            if 200 <= status < 300:
                                action_success = True
                                if path_index > 0:
                                    alternate_path_used = True
                                    alternate_path_successes += 1
                                if credential_attempt > 0:
                                    credential_failover_used = True
                                    credential_failover_successes += 1
                                break

                            if status in PERMISSION_STATUSES and requires_credential:
                                next_headers = _resolver_next_headers(
                                    credential_headers_resolver,
                                    lease,
                                    action,
                                )
                                if next_headers is not None:
                                    credential_attempt += 1
                                    credential_failover_used = True
                                    current_credential_headers = next_headers
                                    continue
                                final_classification = "credential_permission_failure"
                                break

                            if status in ALTERNATE_PATH_HTTP_STATUSES and path_index + 1 < len(paths):
                                alternate_path_used = True
                                final_classification = "predeclared_same_host_failover"
                                break

                            final_classification = "http_failure"
                            break

                        except (ExternalContactError, DiscoveryExternalActionError, OSError, TimeoutError) as exc:
                            classification = _classify_failure(exc)
                            action_attempts.append(
                                {
                                    "path": path,
                                    "error_type": type(exc).__name__,
                                    "classification": classification,
                                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                                    "credential_attempt": credential_attempt,
                                }
                            )
                            final_error = str(exc)[:300]
                            final_classification = classification
                            if classification != "boundary_denial" and path_index + 1 < len(paths):
                                alternate_path_used = True
                            break

                    if action_success:
                        break
                    if final_status in PERMISSION_STATUSES:
                        # Authentication failure is not a reason to probe other paths.
                        break
                    if final_classification == "boundary_denial":
                        break
                    if path_index + 1 >= len(paths):
                        break
                    if not alternate_path_used:
                        break

                credential_context = _resolver_context(
                    credential_headers_resolver,
                    str(action["id"]),
                )
                if action_success:
                    succeeded += 1
                    receipts.append(
                        {
                            "schema": ACTION_RECEIPT_SCHEMA,
                            "ts": int(time.time()),
                            "target": lease.target,
                            "url": final_url,
                            "capability": capability,
                            "action_id": action["id"],
                            "method": method,
                            "status": "success",
                            "http_status": final_status,
                            "final_url": final_url,
                            "response_bytes": final_response_bytes,
                            "response_sha256": final_response_sha256,
                            "elapsed_ms": round((time.monotonic() - action_started) * 1000, 2),
                            "authorization_reference": lease.authorization_reference,
                            "credential_scope": lease.credential_scope,
                            "credential_bound": requires_credential,
                            "credential_context": credential_context,
                            "credential_failover_used": credential_failover_used,
                            "alternate_path_used": alternate_path_used,
                            "payload_source": payload_source,
                            "payload_sha256": payload_sha256,
                            "attempts": action_attempts,
                            "contract": _contract(lease, capability, action),
                        }
                    )
                else:
                    failed += 1
                    row = {
                        "schema": ACTION_RECEIPT_SCHEMA,
                        "ts": int(time.time()),
                        "target": lease.target,
                        "capability": capability,
                        "action_id": action["id"],
                        "method": method,
                        "status": "failed",
                        "http_status": final_status,
                        "final_url": final_url,
                        "classification": final_classification,
                        "decision": (
                            "stop_same_contract"
                            if final_classification in {"boundary_denial", "credential_permission_failure"}
                            else "predeclared_same_host_failover_exhausted"
                        ),
                        "error": final_error,
                        "elapsed_ms": round((time.monotonic() - action_started) * 1000, 2),
                        "authorization_reference": lease.authorization_reference,
                        "credential_scope": lease.credential_scope,
                        "credential_bound": requires_credential,
                        "credential_context": credential_context,
                        "credential_failover_used": credential_failover_used,
                        "alternate_path_used": alternate_path_used,
                        "payload_source": payload_source,
                        "payload_sha256": payload_sha256,
                        "attempts": action_attempts,
                        "contract": _contract(lease, capability, action),
                    }
                    receipts.append(row)
                    _append_ndjson(state / "external_action_denials.ndjson", row)

    flush = getattr(credential_headers_resolver, "flush", None) if credential_headers_resolver is not None else None
    if callable(flush):
        flush()

    payload = {
        "schema": ACTION_RECEIPT_SCHEMA,
        "generated_at": int(time.time()),
        "execution_contract": "active_lease_plus_exact_host_action_profile",
        "canonical_registry_recheck": False,
        # Kept for compatibility: recovery is declared failover, never open-ended exploration.
        "alternate_host_path_or_credential_exploration": False,
        "predeclared_same_host_alternate_path_enabled": True,
        "preprovisioned_credential_failover_enabled": credential_headers_resolver is not None,
        "authority_expansion_on_failure": False,
        "cross_host_failover": False,
        "attempted": attempted,
        "transport_attempts": transport_attempts,
        "succeeded": succeeded,
        "failed": failed,
        "denied_before_execution": denied,
        "alternate_path_successes": alternate_path_successes,
        "credential_failover_successes": credential_failover_successes,
        "receipts": receipts,
    }
    _write_json(state / "discovery_external_action_receipts.json", payload)
    return payload
