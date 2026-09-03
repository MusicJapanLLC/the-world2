"""Authority expansion cases and approved-route execution for explicit owner test hosts.

This runtime increases recovery freedom without treating a denial as permission.
A failed mutation can automatically become an Authority-expansion case.  When the
requested route is still inside an exact, explicitly owner-authorized host and does not
broaden credential scope, the existing owner envelope is sufficient approval for the
route switch.  Anything outside that envelope remains a case only and has no transport
side effect.

Closed loop:

    failed Authority-bound action
      -> expansion case
      -> exact-owner-envelope / decision validation
      -> approved alternate method/path
      -> same credential scope + short-lived credential lease
      -> synthetic payload
      -> POST/PUT/PATCH
      -> receipt / learning

This module never discovers secrets, never carries credentials across hosts, never uses
owner-published external links as authorization, and never creates a new trust root.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host
from .discovery_capability_leases import DiscoveryCapabilityLease, load_discovery_capability_leases
from .discovery_external_action import (
    _action_rows,
    _base_headers,
    _exact_final_url,
    _merge_credential_headers,
    _profile,
)

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy

CASE_SCHEMA = "meta-authority-expansion-cases/v1"
QUEUE_SCHEMA = "meta-authority-expansion-route-queue/v1"
RECEIPT_SCHEMA = "meta-authority-expansion-execution/v1"
ALLOWED_METHODS = frozenset({"POST", "PUT", "PATCH"})
REQUIRED_COUNCIL = frozenset({"META", "X", "SENJU"})
MAX_CASES_PER_CYCLE = 24
MAX_ROUTES_PER_CASE = 6
MAX_EXECUTIONS_PER_CYCLE = 12


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _exact_owner_target(repo_root: Path, host: str) -> dict[str, Any] | None:
    """Resolve only exact explicit-owner targets; link inheritance is intentionally ignored."""
    doc = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    targets = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    if not isinstance(targets, list):
        return None
    try:
        normalized = _normalize_host(host)
    except ValueError:
        return None
    for raw in targets:
        if not isinstance(raw, Mapping) or raw.get("owner_authorization") != "explicit":
            continue
        try:
            candidate = _normalize_host(str(raw.get("host") or ""))
        except ValueError:
            continue
        if candidate == normalized:
            return dict(raw)
    return None


def _source_action(profile: Mapping[str, Any], action_id: str) -> tuple[str, dict[str, Any]] | None:
    for capability in ("credentialed_action", "mutation", "write"):
        for action in _action_rows(profile, capability):
            if str(action.get("id")) == action_id:
                return capability, dict(action)
    return None


def _candidate_routes(profile: Mapping[str, Any], action_id: str) -> tuple[dict[str, Any], ...]:
    expansion = profile.get("authority_expansion", {})
    routes = expansion.get("routes", {}) if isinstance(expansion, Mapping) else {}
    raw_rows = routes.get(action_id, ()) if isinstance(routes, Mapping) else ()
    if not isinstance(raw_rows, list):
        return ()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        method = str(raw.get("method") or "").strip().upper()
        path = str(raw.get("path") or "").strip()
        if method not in ALLOWED_METHODS or not path.startswith("/") or path.startswith("//"):
            continue
        parsed = urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            continue
        safe_path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        key = (method, safe_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "route_id": str(raw.get("route_id") or f"{action_id}:{method}:{safe_path}"),
                "method": method,
                "path": safe_path,
                "priority": max(0, int(raw.get("priority", len(out)))),
            }
        )
        if len(out) >= MAX_ROUTES_PER_CASE:
            break
    out.sort(key=lambda row: (int(row["priority"]), str(row["route_id"])))
    return tuple(out)


def _case_id(target: str, action_id: str, classification: str) -> str:
    digest = hashlib.sha256(f"{target}|{action_id}|{classification}".encode("utf-8")).hexdigest()[:20]
    return f"authority-expansion-{digest}"


def _decision_approved(state: Path, case_id: str) -> bool:
    doc = _load_json(state / "authority_expansion_decisions.json", {})
    rows = doc.get("decisions", ()) if isinstance(doc, Mapping) else ()
    if not isinstance(rows, list):
        return False
    for raw in rows:
        if not isinstance(raw, Mapping) or str(raw.get("case_id")) != case_id:
            continue
        approvers = {
            str(item).strip().upper()
            for item in raw.get("approved_by", [])
            if str(item).strip()
        }
        if raw.get("approved") is True and approvers == REQUIRED_COUNCIL:
            return True
    return False


def _route_inside_owner_envelope(
    *,
    target: Mapping[str, Any] | None,
    profile: Mapping[str, Any],
    source: Mapping[str, Any],
    route: Mapping[str, Any],
) -> tuple[bool, str | None]:
    if target is None:
        return False, "exact_explicit_owner_authorization_missing"
    allowed = {
        str(item).strip().upper()
        for item in target.get("allowed_interactions", [])
        if str(item).strip().upper() in ALLOWED_METHODS
    }
    method = str(route.get("method") or "").upper()
    if method not in allowed:
        return False, "requested_method_not_in_owner_scope"
    expansion = profile.get("authority_expansion", {})
    if not isinstance(expansion, Mapping):
        return False, "authority_expansion_profile_missing"
    if not bool(expansion.get("enabled", False)):
        return False, "authority_expansion_disabled"
    if str(expansion.get("credential_scope_policy") or "same_only") != "same_only":
        return False, "credential_scope_policy_must_be_same_only"
    if bool(source.get("requires_credential")) and str(profile.get("credential_scope") or "none") == "none":
        return False, "credential_scope_missing"
    return True, None


def build_authority_expansion_cases(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    max_cases: int = MAX_CASES_PER_CYCLE,
) -> dict[str, Any]:
    """Turn failed mutation receipts into approval-aware route-switch cases."""
    state = Path(state_dir)
    root = Path(repo_root)
    source = _load_json(state / "discovery_external_action_receipts.json", {})
    receipts = source.get("receipts", ()) if isinstance(source, Mapping) else ()
    previous = _load_json(state / "authority_expansion_cases.json", {})
    previous_rows = previous.get("cases", ()) if isinstance(previous, Mapping) else ()
    previous_by_id = {
        str(row.get("case_id")): row
        for row in previous_rows
        if isinstance(row, Mapping) and row.get("case_id")
    }
    limit = max(1, min(int(max_cases), MAX_CASES_PER_CYCLE))
    now = int(time.time())
    cases: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []

    if not isinstance(receipts, list):
        receipts = []

    for receipt in receipts:
        if len(cases) >= limit:
            break
        if not isinstance(receipt, Mapping) or receipt.get("status") != "failed":
            continue
        target_host = str(receipt.get("target") or "").strip().lower().rstrip(".")
        action_id = str(receipt.get("action_id") or "").strip()
        classification = str(receipt.get("classification") or "external_action_failure").strip()
        if not target_host or not action_id:
            continue
        profile = _profile(state, target_host)
        if profile is None:
            continue
        source_action = _source_action(profile, action_id)
        if source_action is None:
            continue
        capability, action = source_action
        routes = _candidate_routes(profile, action_id)
        if not routes:
            continue
        case_id = _case_id(target_host, action_id, classification)
        old = previous_by_id.get(case_id, {})
        owner_target = _exact_owner_target(root, target_host)
        expansion_cfg = profile.get("authority_expansion", {})
        fastpath = bool(
            isinstance(expansion_cfg, Mapping)
            and expansion_cfg.get("auto_approve_inside_existing_owner_envelope", False)
        )

        approved_routes: list[dict[str, Any]] = []
        blocked_reasons: list[str] = []
        for route in routes:
            inside, reason = _route_inside_owner_envelope(
                target=owner_target,
                profile=profile,
                source=action,
                route=route,
            )
            if not inside:
                if reason and reason not in blocked_reasons:
                    blocked_reasons.append(reason)
                continue
            if fastpath or _decision_approved(state, case_id):
                approved_routes.append(dict(route))

        owner_explicit = owner_target is not None
        approved = bool(approved_routes)
        if approved:
            stage = "approved_route_ready"
            blocking_reason = None
            next_action = "execute_approved_route_switch"
            approval_basis = (
                "existing_explicit_owner_envelope"
                if fastpath
                else "META_X_SENJU_3_of_3"
            )
        else:
            stage = "awaiting_approval" if owner_explicit else "external_authorization_required"
            blocking_reason = (
                blocked_reasons[0]
                if blocked_reasons
                else (
                    "awaiting_META_X_SENJU_3_of_3"
                    if owner_explicit
                    else "exact_explicit_owner_authorization_missing"
                )
            )
            next_action = (
                "META_coordinate_authority_expansion_review"
                if owner_explicit
                else "META_collect_explicit_authorization"
            )
            approval_basis = None

        case = {
            "schema": CASE_SCHEMA,
            "case_id": case_id,
            "target": target_host,
            "source_action_id": action_id,
            "source_capability": capability,
            "source_method": str(action.get("method")),
            "source_classification": classification,
            "credential_bound": bool(action.get("requires_credential")),
            "credential_scope": str(profile.get("credential_scope") or "none"),
            "requested_routes": [dict(route) for route in routes],
            "approved_routes": approved_routes,
            "current_stage": stage,
            "blocking_reason": blocking_reason,
            "next_action": next_action,
            "approval_basis": approval_basis,
            "approval_coordinator": "META",
            "required_approvers": ["META", "X", "SENJU"],
            "exact_explicit_owner_authorization_present": owner_explicit,
            "cross_host_expansion_allowed": False,
            "credential_scope_expansion_allowed": False,
            "first_seen_at": int(old.get("first_seen_at", now)),
            "last_progress_at": now if str(old.get("current_stage")) != stage else int(old.get("last_progress_at", now)),
        }
        cases.append(case)
        if approved:
            queue.append(
                {
                    "case_id": case_id,
                    "target": target_host,
                    "source_action_id": action_id,
                    "source_capability": capability,
                    "credential_scope": case["credential_scope"],
                    "routes": approved_routes,
                    "approval_basis": approval_basis,
                }
            )

    result = {
        "schema": CASE_SCHEMA,
        "generated_at": now,
        "cases": cases,
        "case_count": len(cases),
        "approved_route_cases": sum(1 for row in cases if row["current_stage"] == "approved_route_ready"),
        "waiting_cases": sum(1 for row in cases if row["current_stage"] != "approved_route_ready"),
        "auto_case_generation": True,
        "owner_envelope_fastpath": True,
        "cross_host_transport_from_expansion": False,
    }
    queue_doc = {
        "schema": QUEUE_SCHEMA,
        "generated_at": now,
        "routes": queue,
        "route_case_count": len(queue),
    }
    _write_json(state / "authority_expansion_cases.json", result)
    _write_json(state / "authority_expansion_route_queue.json", queue_doc)
    return result


def _resolve_payload(payload_resolver: Any, lease: DiscoveryCapabilityLease, action: Mapping[str, Any]) -> tuple[bytes | None, str]:
    if payload_resolver is None:
        body = action.get("body")
        return (str(body).encode("utf-8") if body is not None else None), "declared_owner_profile"
    resolved = payload_resolver(lease, action)
    body = getattr(resolved, "body", resolved)
    source = str(getattr(resolved, "source", "runtime_resolver"))
    if body is not None and not isinstance(body, bytes):
        raise ValueError("expansion payload resolver must return bytes or None")
    return body, source


def execute_approved_authority_expansion_routes(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    credential_headers_resolver: Any = None,
    payload_resolver: Any = None,
    max_executions: int = MAX_EXECUTIONS_PER_CYCLE,
) -> dict[str, Any]:
    """Execute only routes approved by the expansion case builder."""
    state = Path(state_dir)
    root = Path(repo_root)
    queue_doc = _load_json(state / "authority_expansion_route_queue.json", {})
    rows = queue_doc.get("routes", ()) if isinstance(queue_doc, Mapping) else ()
    if not isinstance(rows, list):
        rows = []
    leases = {
        lease.target: lease
        for lease in load_discovery_capability_leases(state)
        if lease.is_active()
    }
    limit = max(1, min(int(max_executions), MAX_EXECUTIONS_PER_CYCLE))
    executed = 0
    transport_attempts = 0
    succeeded = 0
    failed = 0
    receipts: list[dict[str, Any]] = []

    for row in rows:
        if executed >= limit:
            break
        if not isinstance(row, Mapping):
            continue
        target = str(row.get("target") or "").strip().lower().rstrip(".")
        lease = leases.get(target)
        if lease is None or _exact_owner_target(root, target) is None:
            continue
        profile = _profile(state, target)
        if profile is None:
            continue
        source = _source_action(profile, str(row.get("source_action_id") or ""))
        if source is None:
            continue
        capability, base_action = source
        requires_credential = bool(base_action.get("requires_credential"))
        if str(row.get("credential_scope") or "none") != lease.credential_scope:
            continue
        case_success = False

        for route in row.get("routes", []):
            if executed >= limit or case_success:
                break
            if not isinstance(route, Mapping):
                continue
            method = str(route.get("method") or "").upper()
            path = str(route.get("path") or "")
            owner_target = _exact_owner_target(root, target)
            inside, _ = _route_inside_owner_envelope(
                target=owner_target,
                profile=profile,
                source=base_action,
                route=route,
            )
            if not inside:
                continue
            action = dict(base_action)
            action["method"] = method
            action["path"] = path
            action["id"] = str(base_action["id"])
            try:
                body, payload_source = _resolve_payload(payload_resolver, lease, action)
                base_headers = _base_headers(action, body=body)
                credential_headers: Mapping[str, str] = {}
                if requires_credential:
                    if credential_headers_resolver is None:
                        raise ValueError("credential binding adapter unavailable")
                    credential_headers = credential_headers_resolver(lease, action)
                current_headers = credential_headers
                credential_attempt = 0
                while True:
                    headers = _merge_credential_headers(base_headers, current_headers)
                    url = urllib.parse.urlunsplit(("https", target, path, "", ""))
                    policy = ExternalContactPolicy.from_hosts(
                        [target],
                        allow_http=False,
                        allow_delete=False,
                        follow_redirects=False,
                        timeout_seconds=8.0,
                        max_response_bytes=256 * 1024,
                        retries=1,
                    )
                    executed += 1
                    transport_attempts += 1
                    result = ExternalContactClient(policy).contact_with_body(
                        url,
                        method=method,
                        body=body,
                        headers=headers,
                    )
                    status = int(result.receipt.status)
                    if not _exact_final_url(target, str(result.receipt.final_url)):
                        raise ValueError("expansion route escaped exact owner host")
                    report = getattr(credential_headers_resolver, "report_http_status", None)
                    if callable(report):
                        report(str(action["id"]), status)
                    if 200 <= status < 300:
                        succeeded += 1
                        case_success = True
                        receipts.append(
                            {
                                "case_id": str(row.get("case_id")),
                                "target": target,
                                "action_id": str(action["id"]),
                                "method": method,
                                "path": path,
                                "status": "success",
                                "http_status": status,
                                "credential_bound": requires_credential,
                                "credential_attempt": credential_attempt,
                                "payload_source": payload_source,
                                "approval_basis": row.get("approval_basis"),
                                "cross_host": False,
                            }
                        )
                        break
                    if status in {401, 403} and requires_credential:
                        next_headers = getattr(credential_headers_resolver, "next_headers", None)
                        replacement = next_headers(lease, action) if callable(next_headers) else None
                        if isinstance(replacement, Mapping):
                            credential_attempt += 1
                            current_headers = replacement
                            continue
                    failed += 1
                    receipts.append(
                        {
                            "case_id": str(row.get("case_id")),
                            "target": target,
                            "action_id": str(action["id"]),
                            "method": method,
                            "path": path,
                            "status": "failed",
                            "http_status": status,
                            "credential_bound": requires_credential,
                            "credential_attempt": credential_attempt,
                            "payload_source": payload_source,
                            "approval_basis": row.get("approval_basis"),
                            "cross_host": False,
                        }
                    )
                    break
            except (ExternalContactError, OSError, TimeoutError, ValueError) as exc:
                failed += 1
                receipts.append(
                    {
                        "case_id": str(row.get("case_id")),
                        "target": target,
                        "action_id": str(base_action.get("id")),
                        "method": method,
                        "path": path,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "approval_basis": row.get("approval_basis"),
                        "cross_host": False,
                    }
                )
                continue

    flush = getattr(credential_headers_resolver, "flush", None) if credential_headers_resolver is not None else None
    if callable(flush):
        flush()
    result = {
        "schema": RECEIPT_SCHEMA,
        "generated_at": int(time.time()),
        "executed": executed,
        "transport_attempts": transport_attempts,
        "succeeded": succeeded,
        "failed": failed,
        "same_exact_owner_host_only": True,
        "credential_scope_expansion": False,
        "new_trust_root_creation": False,
        "receipts": receipts,
    }
    _write_json(state / "authority_expansion_execution_receipts.json", result)
    return result
