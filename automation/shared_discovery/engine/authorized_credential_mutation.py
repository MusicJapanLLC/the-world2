"""Credential-bound mutation bundle for explicit owner-authorized synthetic test targets.

This module binds three existing concepts into one bounded execution lane:

    Authority capability lease
      + explicitly registered synthetic credential
      + owner-declared POST/PUT/PATCH mutation

It is intentionally NOT a credential harvesting or privilege-escalation mechanism.
Credential selection only considers environment-variable names explicitly declared in
an owner-controlled plan. It never scans environment variables, filesystems, browsers,
logs, repositories, cloud metadata, or third-party services for secrets.

Failure recovery is bounded to predeclared same-origin alternate paths and structured
synthetic payload variants. It never changes host, discovers new paths, widens methods,
expands Authority, or changes credential scope after a failure.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .discovery_authorization import _normalize_host
from .discovery_capability_leases import authorize_discovery_capability

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

SCHEMA = "the-world-authorized-credential-mutation/v1"
PLAN_SCHEMA = "the-world-authorized-credential-mutation-plan/v1"
RECEIPT_SCHEMA = "the-world-authorized-credential-mutation-receipts/v1"
ALLOWED_METHODS = frozenset({"POST", "PUT", "PATCH"})
MAX_ATTEMPTS_PER_ACTION = 4
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 128 * 1024


class AuthorizedCredentialMutationError(RuntimeError):
    """Fail-closed validation/execution error for the credential mutation lane."""


@dataclasses.dataclass(frozen=True)
class SyntheticCredentialBinding:
    credential_id: str
    env_var: str
    header: str
    prefix: str
    target: str


@dataclasses.dataclass(frozen=True)
class MutationAttempt:
    action_id: str
    target: str
    method: str
    path: str
    attempt: int
    payload_variant: int
    authority_lease_id: str | None
    credential_id: str | None
    status: str
    http_status: int | None = None
    response_bytes: int = 0
    response_sha256: str | None = None
    error_type: str | None = None
    error: str | None = None


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _explicit_target_methods(repo_root: Path) -> dict[str, frozenset[str]]:
    doc = _load(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    targets = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    result: dict[str, frozenset[str]] = {}
    if not isinstance(targets, list):
        return result
    for row in targets:
        if not isinstance(row, Mapping) or row.get("owner_authorization") != "explicit":
            continue
        try:
            host = _normalize_host(str(row.get("host") or ""))
        except ValueError:
            continue
        methods = frozenset(
            str(value).strip().upper()
            for value in row.get("allowed_interactions", ())
            if str(value).strip().upper() in ALLOWED_METHODS
        )
        result[host] = methods
    return result


def _safe_path(raw: object) -> str:
    value = str(raw or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        raise AuthorizedCredentialMutationError("mutation path must be an absolute same-origin path")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise AuthorizedCredentialMutationError("mutation path may not change origin or contain a fragment")
    if any(part == ".." for part in parsed.path.split("/")):
        raise AuthorizedCredentialMutationError("parent-path traversal is not allowed in mutation paths")
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


def _action_paths(action: Mapping[str, Any]) -> tuple[str, ...]:
    values = [_safe_path(action.get("path"))]
    raw_alt = action.get("alternate_paths", ())
    if raw_alt is not None and not isinstance(raw_alt, list):
        raise AuthorizedCredentialMutationError("alternate_paths must be a list")
    for raw in raw_alt or ():
        path = _safe_path(raw)
        if path not in values:
            values.append(path)
    return tuple(values[:MAX_ATTEMPTS_PER_ACTION])


def _payload_variants(action: Mapping[str, Any], *, trace_id: str) -> tuple[bytes, ...]:
    content_type = str(action.get("content_type") or "application/json").strip().lower()
    raw = action.get("body")
    if raw is None:
        raw = "{}" if "json" in content_type else ""
    if not isinstance(raw, str):
        raise AuthorizedCredentialMutationError("mutation body must be a string")

    variants: list[str] = [raw]
    if "json" in content_type:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise AuthorizedCredentialMutationError("JSON mutation body is invalid") from exc
        if not isinstance(parsed, dict):
            raise AuthorizedCredentialMutationError("JSON mutation body must be an object")
        for idx in (1, 2):
            varied = dict(parsed)
            varied["_synthetic_test_trace"] = trace_id
            varied["_synthetic_test_variant"] = idx
            variants.append(json.dumps(varied, ensure_ascii=False, separators=(",", ":")))
    elif "x-www-form-urlencoded" in content_type:
        sep = "&" if raw else ""
        variants.append(f"{raw}{sep}_synthetic_test_trace={trace_id}&_synthetic_test_variant=1")
        variants.append(f"{raw}{sep}_synthetic_test_trace={trace_id}&_synthetic_test_variant=2")

    encoded: list[bytes] = []
    for value in variants:
        body = value.encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise AuthorizedCredentialMutationError("generated mutation payload exceeds request limit")
        if body not in encoded:
            encoded.append(body)
    return tuple(encoded)


def _credential_binding(
    plan: Mapping[str, Any],
    *,
    target: str,
    environ: Mapping[str, str],
) -> tuple[SyntheticCredentialBinding | None, str | None]:
    raw = plan.get("synthetic_credentials", ())
    if not isinstance(raw, list):
        raise AuthorizedCredentialMutationError("synthetic_credentials must be a list")

    declared: list[SyntheticCredentialBinding] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        if row.get("synthetic_only") is not True:
            continue
        if _normalize_host(str(row.get("target") or target)) != target:
            continue
        credential_id = str(row.get("credential_id") or "").strip()
        env_var = str(row.get("env_var") or "").strip()
        header = str(row.get("header") or "Authorization").strip()
        prefix = str(row.get("prefix") or "")
        if not credential_id or not env_var.startswith("AUTHORIZED_TEST_"):
            continue
        if header.lower() not in {"authorization", "x-test-token", "x-synthetic-token"}:
            continue
        declared.append(SyntheticCredentialBinding(credential_id, env_var, header, prefix, target))

    for binding in declared:
        if environ.get(binding.env_var):
            return binding, environ[binding.env_var]
    return (declared[0], None) if declared else (None, None)


def _validate_plan(plan: Mapping[str, Any], repo_root: Path) -> tuple[str, Sequence[Mapping[str, Any]]]:
    if str(plan.get("schema") or PLAN_SCHEMA) != PLAN_SCHEMA:
        raise AuthorizedCredentialMutationError("unsupported credential mutation plan schema")
    if plan.get("mode") != "synthetic_test_only":
        raise AuthorizedCredentialMutationError("credential mutation plan must use synthetic_test_only mode")
    target = _normalize_host(str(plan.get("target") or ""))
    explicit = _explicit_target_methods(repo_root)
    if target not in explicit:
        raise AuthorizedCredentialMutationError("target is not an exact explicit owner-authorized test host")
    actions = plan.get("actions", ())
    if not isinstance(actions, list) or not actions:
        raise AuthorizedCredentialMutationError("credential mutation plan requires actions")
    for action in actions:
        if not isinstance(action, Mapping):
            raise AuthorizedCredentialMutationError("every mutation action must be an object")
        method = str(action.get("method") or "").strip().upper()
        if method not in ALLOWED_METHODS:
            raise AuthorizedCredentialMutationError("only POST/PUT/PATCH are supported")
        if method not in explicit[target]:
            raise AuthorizedCredentialMutationError(f"method {method} is not explicitly authorized for {target}")
        _action_paths(action)
        _payload_variants(action, trace_id="validation")
    return target, actions


def _client(target: str, method: str, factory: Callable[[ExternalContactPolicy], Any] | None) -> Any:
    policy = ExternalContactPolicy(
        allow_hosts=frozenset({target}),
        allow_http=False,
        allowed_methods=frozenset({method}),
        allow_delete=False,
        follow_redirects=False,
        max_redirects=0,
        timeout_seconds=8.0,
        max_request_bytes=MAX_REQUEST_BYTES,
        max_response_bytes=MAX_RESPONSE_BYTES,
        retries=0,
    )
    return factory(policy) if factory is not None else ExternalContactClient(policy)


def run_authorized_credential_mutation(
    plan_path: str | Path,
    *,
    repo_root: str | Path,
    state_dir: str | Path,
    execute: bool = False,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[ExternalContactPolicy], Any] | None = None,
    authority_resolver: Callable[..., Any] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    state = Path(state_dir)
    current = int(time.time()) if now is None else int(now)
    plan = _load(Path(plan_path), {})
    if not isinstance(plan, Mapping):
        raise AuthorizedCredentialMutationError("credential mutation plan must be an object")
    target, actions = _validate_plan(plan, root)
    env = dict(os.environ if environ is None else environ)
    binding, secret = _credential_binding(plan, target=target, environ=env)

    trace_id = hashlib.sha256(f"{target}:{current}".encode()).hexdigest()[:16]
    attempts: list[MutationAttempt] = []
    planned_attempts = 0
    for action in actions:
        planned_attempts += min(len(_action_paths(action)), MAX_ATTEMPTS_PER_ACTION)

    if not execute:
        result = {
            "schema": SCHEMA,
            "mode": "dry_run",
            "target": target,
            "authority_lease_required": True,
            "credential_binding_required": True,
            "credential_discovery_mode": "declared_synthetic_metadata_only",
            "credential_id": binding.credential_id if binding else None,
            "credential_available": secret is not None,
            "credential_secret_recorded": False,
            "payload_generation": "bounded_structured_synthetic_variants",
            "alternate_path_mode": "predeclared_same_origin_only",
            "planned_action_count": len(actions),
            "planned_attempt_count": planned_attempts,
            "external_side_effects": False,
        }
        _write(state / "authorized_credential_mutation_result.json", result)
        return result

    if binding is None:
        raise AuthorizedCredentialMutationError("no declared synthetic credential binding exists")
    if secret is None:
        raise AuthorizedCredentialMutationError("declared synthetic credential is not provisioned")

    resolver = authority_resolver or authorize_discovery_capability
    succeeded = 0
    failed = 0
    for action in actions:
        action_id = str(action.get("id") or "").strip()
        method = str(action.get("method") or "").strip().upper()
        capability = "write" if method == "POST" else "mutation"
        content_type = str(action.get("content_type") or "application/json").strip()
        paths = _action_paths(action)
        payloads = _payload_variants(action, trace_id=trace_id)
        done = False

        for index, path in enumerate(paths):
            if done:
                break
            payload = payloads[min(index, len(payloads) - 1)]
            lease = resolver(state, target=target, capability=capability, now=current)
            lease_id = str(getattr(lease, "lease_id", "")) or None
            url = urllib.parse.urlunsplit(("https", target, urllib.parse.urlsplit(path).path, urllib.parse.urlsplit(path).query, ""))
            headers = {
                "Content-Type": content_type,
                binding.header: binding.prefix + secret,
                "X-Synthetic-Test-Trace": trace_id,
            }
            try:
                client = _client(target, method, client_factory)
                response = client.contact_with_body(url, method=method, body=payload, headers=headers)
                status = int(response.receipt.status)
                body = bytes(response.body)
                ok = 200 <= status < 400
                attempts.append(MutationAttempt(
                    action_id=action_id,
                    target=target,
                    method=method,
                    path=path,
                    attempt=index + 1,
                    payload_variant=min(index, len(payloads) - 1),
                    authority_lease_id=lease_id,
                    credential_id=binding.credential_id,
                    status="success" if ok else "failed",
                    http_status=status,
                    response_bytes=len(body),
                    response_sha256=hashlib.sha256(body).hexdigest(),
                ))
                if ok:
                    succeeded += 1
                    done = True
                else:
                    failed += 1
            except (ExternalContactError, OSError, TimeoutError, AuthorizedCredentialMutationError) as exc:
                failed += 1
                attempts.append(MutationAttempt(
                    action_id=action_id,
                    target=target,
                    method=method,
                    path=path,
                    attempt=index + 1,
                    payload_variant=min(index, len(payloads) - 1),
                    authority_lease_id=lease_id,
                    credential_id=binding.credential_id,
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:240],
                ))

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "generated_at": current,
        "target": target,
        "credential_id": binding.credential_id,
        "credential_env_var": binding.env_var,
        "credential_secret_recorded": False,
        "credential_inherited_across_attempts": True,
        "authority_revalidated_before_every_attempt": True,
        "host_changed_after_failure": False,
        "method_widened_after_failure": False,
        "credential_scope_widened_after_failure": False,
        "alternate_path_mode": "predeclared_same_origin_only",
        "payload_generation": "bounded_structured_synthetic_variants",
        "succeeded": succeeded,
        "failed_attempts": failed,
        "attempts": [dataclasses.asdict(row) for row in attempts],
    }
    _write(state / "authorized_credential_mutation_receipts.json", receipt)
    result = {
        "schema": SCHEMA,
        "mode": "execute",
        "target": target,
        "action_count": len(actions),
        "attempt_count": len(attempts),
        "succeeded": succeeded,
        "failed_attempts": failed,
        "credential_id": binding.credential_id,
        "credential_secret_recorded": False,
        "receipt_path": str(state / "authorized_credential_mutation_receipts.json"),
    }
    _write(state / "authorized_credential_mutation_result.json", result)
    return result
