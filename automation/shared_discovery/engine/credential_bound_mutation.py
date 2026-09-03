"""Credential-bound POST/PUT/PATCH for explicitly authorized synthetic test targets.

Bundle:
    live Authority lease
      + named test-credential binding
      + credential-scope inheritance
      + agent-generated synthetic payload variants
      + POST/PUT/PATCH
      + same-host alternate-path retry

The executor is intentionally narrow:
- only exact hosts explicitly owner-authorized in AUTHORIZED_TEST_TARGETS.json;
- only credentials named by a repository binding and supplied through the named env var;
- secrets are never written to state, receipts, logs, or payloads;
- credential scope must match the live capability lease;
- every attempt re-validates both credentialed_action and write/mutation capability;
- retries may vary payload/path only inside the same exact HTTPS host;
- no authority expansion, cross-host failover, secret harvesting, or credential reuse.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.parse as urlparse
from pathlib import Path
from typing import Any, Callable, Mapping

from .discovery_authorization import _load_json, _normalize_host
from .discovery_capability_leases import (
    DiscoveryCapabilityLease,
    DiscoveryCapabilityLeaseError,
    authorize_discovery_capability,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

CONFIG_SCHEMA = "the-world-credential-bound-mutation-config/v1"
RECEIPT_SCHEMA = "the-world-credential-bound-mutation-receipts/v1"
ALLOWED_METHODS = frozenset({"POST", "PUT", "PATCH"})
ALLOWED_HEADERS = frozenset({"authorization", "x-api-key"})
MAX_REQUEST_BYTES_HARD = 64 * 1024
MAX_RESPONSE_BYTES_HARD = 256 * 1024
MAX_MUTATIONS_HARD = 16
MAX_ATTEMPTS_HARD = 8


class CredentialBoundMutationError(RuntimeError):
    """Fail-closed error for invalid Authority/Credential/Mutation bundles."""


@dataclasses.dataclass(frozen=True)
class CredentialBinding:
    binding_id: str
    host: str
    credential_scope: str
    secret_env: str
    header: str
    prefix: str
    methods: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MutationAttemptReceipt:
    mutation_id: str
    host: str
    capability: str
    method: str
    path: str
    status: str
    attempted_at: int
    lease_id: str | None
    credential_scope: str | None
    credential_binding: str | None
    payload_variant: int | None
    payload_sha256: str | None
    alternate_path: bool
    http_status: int | None = None
    final_url: str | None = None
    response_bytes: int = 0
    response_sha256: str | None = None
    error_type: str | None = None
    error: str | None = None


def _explicit_owner_hosts(repo_root: Path) -> set[str]:
    doc = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    rows = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    hosts: set[str] = set()
    if not isinstance(rows, list):
        return hosts
    for row in rows:
        if not isinstance(row, Mapping) or row.get("owner_authorization") != "explicit":
            continue
        raw = str(row.get("host") or "").strip()
        if not raw:
            continue
        try:
            hosts.add(_normalize_host(raw))
        except ValueError:
            continue
    return hosts


def _config(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "automation" / "codegen" / "config" / "credential_bound_mutation.json"
    doc = _load_json(path, {})
    if not isinstance(doc, Mapping) or doc.get("schema") != CONFIG_SCHEMA:
        raise CredentialBoundMutationError("credential-bound mutation config is missing or invalid")
    return dict(doc)


def _limits(config: Mapping[str, Any]) -> tuple[int, int, int, int]:
    raw = config.get("limits", {})
    if not isinstance(raw, Mapping):
        raw = {}
    mutations = max(1, min(int(raw.get("max_mutations_per_cycle", 6) or 6), MAX_MUTATIONS_HARD))
    attempts = max(1, min(int(raw.get("max_attempts_per_mutation", 6) or 6), MAX_ATTEMPTS_HARD))
    request_bytes = max(1024, min(int(raw.get("max_request_bytes", 16384) or 16384), MAX_REQUEST_BYTES_HARD))
    response_bytes = max(4096, min(int(raw.get("max_response_bytes", 131072) or 131072), MAX_RESPONSE_BYTES_HARD))
    return mutations, attempts, request_bytes, response_bytes


def _bindings(config: Mapping[str, Any]) -> dict[str, CredentialBinding]:
    out: dict[str, CredentialBinding] = {}
    rows = config.get("bindings", ())
    if not isinstance(rows, list):
        return out
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("owner_authorization") != "explicit" or raw.get("synthetic_only") is not True:
            continue
        try:
            host = _normalize_host(str(raw.get("host") or ""))
        except ValueError:
            continue
        binding_id = str(raw.get("id") or "").strip()
        credential_scope = str(raw.get("credential_scope") or "").strip()
        secret_env = str(raw.get("secret_env") or "").strip()
        header = str(raw.get("header") or "").strip()
        prefix = str(raw.get("prefix") or "")
        methods = tuple(
            sorted({str(v).strip().upper() for v in raw.get("methods", ()) if str(v).strip().upper() in ALLOWED_METHODS})
        )
        if not binding_id or not credential_scope or not secret_env or header.lower() not in ALLOWED_HEADERS or not methods:
            continue
        out[binding_id] = CredentialBinding(
            binding_id=binding_id,
            host=host,
            credential_scope=credential_scope,
            secret_env=secret_env,
            header=header,
            prefix=prefix,
            methods=methods,
        )
    return out


def _credential_for(
    binding: CredentialBinding,
    *,
    lease: DiscoveryCapabilityLease,
    method: str,
    environ: Mapping[str, str],
) -> str:
    if binding.host != lease.target:
        raise CredentialBoundMutationError("credential binding host does not match Authority lease")
    if binding.credential_scope != lease.credential_scope:
        raise CredentialBoundMutationError("credential binding scope does not match Authority lease")
    if method not in binding.methods:
        raise CredentialBoundMutationError("credential binding does not permit mutation method")
    value = str(environ.get(binding.secret_env, ""))
    if not value:
        raise CredentialBoundMutationError(f"configured test credential is unavailable: {binding.secret_env}")
    if "\r" in value or "\n" in value:
        raise CredentialBoundMutationError("configured test credential contains invalid control characters")
    return value


def _same_host_url(host: str, raw_path: object) -> tuple[str, str]:
    path = str(raw_path or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        raise CredentialBoundMutationError("mutation path must be an absolute same-origin path")
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise CredentialBoundMutationError("mutation path may not change origin or include a fragment")
    clean_path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, "")), clean_path


def _payload_bytes(spec: Mapping[str, Any], *, variant: int, now: int, max_bytes: int) -> bytes:
    mode = str(spec.get("payload_mode") or "").strip()
    static = spec.get("static_fields", {})
    if not isinstance(static, Mapping):
        raise CredentialBoundMutationError("static_fields must be an object")
    fields = {str(k): v for k, v in static.items()}
    fields.update({
        "synthetic": True,
        "generated_by": "credential-bound-mutation-agent",
        "mutation_id": str(spec.get("id") or ""),
        "payload_variant": int(variant),
        "generated_at": int(now),
    })
    if mode == "json_synthetic":
        body = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif mode == "form_synthetic":
        body = urlparse.urlencode({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fields.items()}).encode("utf-8")
    else:
        raise CredentialBoundMutationError("unsupported synthetic payload mode")
    if len(body) > max_bytes:
        raise CredentialBoundMutationError("generated synthetic payload exceeds request limit")
    return body


def _attempt_plan(spec: Mapping[str, Any], *, max_attempts: int) -> list[tuple[str, int, bool]]:
    primary = str(spec.get("primary_path") or "").strip()
    alternates = spec.get("alternate_paths", ())
    if not isinstance(alternates, list):
        alternates = []
    paths = [primary] + [str(v).strip() for v in alternates if str(v).strip()]
    variants = max(1, min(int(spec.get("payload_variants", 1) or 1), 4))
    plan: list[tuple[str, int, bool]] = []
    for path_index, path in enumerate(paths):
        for variant in range(variants):
            plan.append((path, variant, path_index > 0))
            if len(plan) >= max_attempts:
                return plan
    return plan


def _client(host: str, method: str, *, request_bytes: int, response_bytes: int, client_factory: Callable[[ExternalContactPolicy], Any] | None) -> Any:
    policy = ExternalContactPolicy(
        allow_hosts=frozenset({host}),
        allow_http=False,
        allowed_methods=frozenset({method}),
        allow_delete=False,
        follow_redirects=False,
        max_redirects=0,
        timeout_seconds=8.0,
        max_request_bytes=request_bytes,
        max_response_bytes=response_bytes,
        retries=0,
    )
    return client_factory(policy) if client_factory is not None else ExternalContactClient(policy)


def _verify_final_url(host: str, final_url: str) -> None:
    parsed = urllib.parse.urlsplit(str(final_url))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise CredentialBoundMutationError("mutation returned a non-HTTPS final URL")
    try:
        final_host = _normalize_host(parsed.hostname)
    except ValueError as exc:
        raise CredentialBoundMutationError("mutation returned invalid final host") from exc
    if final_host != host or parsed.port not in (None, 443):
        raise CredentialBoundMutationError("mutation final URL escaped exact authorized host")


def _receipt_document(receipts: list[MutationAttemptReceipt], *, planned_mutations: int, credential_available: int) -> dict[str, Any]:
    terminal = {row.mutation_id for row in receipts if row.status == "success"}
    denied = {row.mutation_id for row in receipts if row.status == "denied"}
    return {
        "schema": RECEIPT_SCHEMA,
        "generated_at": int(time.time()),
        "planned_mutations": planned_mutations,
        "successful_mutations": len(terminal),
        "denied_mutations": len(denied),
        "attempt_count": len(receipts),
        "credential_bindings_available": credential_available,
        "credential_auto_discovery": "named_repository_binding_plus_named_environment_secret",
        "credential_inheritance": "binding_scope_must_equal_live_Authority_lease_scope",
        "agent_generated_payloads": True,
        "allowed_methods": sorted(ALLOWED_METHODS),
        "alternate_path_policy": "same_exact_authorized_host_only",
        "authority_expansion_on_failure": False,
        "credential_scope_expansion_on_failure": False,
        "cross_host_failover": False,
        "secret_persisted": False,
        "receipts": [dataclasses.asdict(row) for row in receipts],
    }


def execute_credential_bound_mutations(
    state_dir: str | Path,
    *,
    repo_root: str | Path = _REPO_ROOT,
    environ: Mapping[str, str] | None = None,
    now: int | None = None,
    client_factory: Callable[[ExternalContactPolicy], Any] | None = None,
    receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    root = Path(repo_root)
    current = int(time.time()) if now is None else int(now)
    env = os.environ if environ is None else environ
    config = _config(root)
    bindings = _bindings(config)
    explicit_hosts = _explicit_owner_hosts(root)
    max_mutations, max_attempts, max_request, max_response = _limits(config)
    rows = config.get("mutations", ())
    mutations = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    receipts: list[MutationAttemptReceipt] = []
    credential_available = sum(1 for binding in bindings.values() if str(env.get(binding.secret_env, "")))

    for spec in mutations[:max_mutations]:
        mutation_id = str(spec.get("id") or "").strip()
        method = str(spec.get("method") or "").strip().upper()
        capability = str(spec.get("capability") or "").strip().lower()
        binding_id = str(spec.get("credential_binding") or "").strip()
        try:
            host = _normalize_host(str(spec.get("host") or ""))
        except ValueError:
            host = ""
        if not mutation_id or host not in explicit_hosts or method not in ALLOWED_METHODS or capability not in {"write", "mutation"}:
            receipts.append(MutationAttemptReceipt(
                mutation_id=mutation_id or "invalid-mutation",
                host=host,
                capability=capability,
                method=method,
                path=str(spec.get("primary_path") or ""),
                status="denied",
                attempted_at=current,
                lease_id=None,
                credential_scope=None,
                credential_binding=binding_id or None,
                payload_variant=None,
                payload_sha256=None,
                alternate_path=False,
                error_type="CredentialBoundMutationError",
                error="mutation is outside exact explicit owner-authorized synthetic scope",
            ))
            continue

        binding = bindings.get(binding_id)
        try:
            lease = authorize_discovery_capability(state, target=host, capability="credentialed_action", now=current)
            capability_lease = authorize_discovery_capability(state, target=host, capability=capability, now=current)
            if capability_lease.lease_id != lease.lease_id:
                raise DiscoveryCapabilityLeaseError("credentialed and mutation capability are not on the same current lease")
            if binding is None:
                raise CredentialBoundMutationError("named credential binding does not exist")
            secret = _credential_for(binding, lease=lease, method=method, environ=env)
        except (DiscoveryCapabilityLeaseError, CredentialBoundMutationError) as exc:
            receipts.append(MutationAttemptReceipt(
                mutation_id=mutation_id,
                host=host,
                capability=capability,
                method=method,
                path=str(spec.get("primary_path") or ""),
                status="denied",
                attempted_at=current,
                lease_id=None,
                credential_scope=None,
                credential_binding=binding_id or None,
                payload_variant=None,
                payload_sha256=None,
                alternate_path=False,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            ))
            continue

        for raw_path, variant, alternate in _attempt_plan(spec, max_attempts=max_attempts):
            try:
                live = authorize_discovery_capability(state, target=host, capability="credentialed_action", now=current)
                live_cap = authorize_discovery_capability(state, target=host, capability=capability, now=current)
                if live.lease_id != lease.lease_id or live_cap.lease_id != lease.lease_id:
                    raise DiscoveryCapabilityLeaseError("Authority lease changed during mutation sequence")
                if live.credential_scope != binding.credential_scope:
                    raise CredentialBoundMutationError("credential scope changed during mutation sequence")
                url, clean_path = _same_host_url(host, raw_path)
                body = _payload_bytes(spec, variant=variant, now=current, max_bytes=max_request)
                headers = {
                    binding.header: binding.prefix + secret,
                    "Content-Type": str(spec.get("content_type") or "application/json"),
                    "X-The-World-Synthetic-Test": "true",
                }
                client = _client(host, method, request_bytes=max_request, response_bytes=max_response, client_factory=client_factory)
                result = client.contact_with_body(url, method=method, body=body, headers=headers)
                _verify_final_url(host, str(result.receipt.final_url))
                response = bytes(result.body)
                receipts.append(MutationAttemptReceipt(
                    mutation_id=mutation_id,
                    host=host,
                    capability=capability,
                    method=method,
                    path=clean_path,
                    status="success",
                    attempted_at=current,
                    lease_id=lease.lease_id,
                    credential_scope=lease.credential_scope,
                    credential_binding=binding.binding_id,
                    payload_variant=variant,
                    payload_sha256=hashlib.sha256(body).hexdigest(),
                    alternate_path=alternate,
                    http_status=int(result.receipt.status),
                    final_url=str(result.receipt.final_url),
                    response_bytes=len(response),
                    response_sha256=hashlib.sha256(response).hexdigest(),
                ))
                break
            except (DiscoveryCapabilityLeaseError, CredentialBoundMutationError) as exc:
                receipts.append(MutationAttemptReceipt(
                    mutation_id=mutation_id,
                    host=host,
                    capability=capability,
                    method=method,
                    path=str(raw_path),
                    status="denied",
                    attempted_at=current,
                    lease_id=lease.lease_id,
                    credential_scope=lease.credential_scope,
                    credential_binding=binding.binding_id,
                    payload_variant=variant,
                    payload_sha256=None,
                    alternate_path=alternate,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                ))
                break
            except (ExternalContactError, OSError, TimeoutError) as exc:
                receipts.append(MutationAttemptReceipt(
                    mutation_id=mutation_id,
                    host=host,
                    capability=capability,
                    method=method,
                    path=str(raw_path),
                    status="failed",
                    attempted_at=current,
                    lease_id=lease.lease_id,
                    credential_scope=lease.credential_scope,
                    credential_binding=binding.binding_id,
                    payload_variant=variant,
                    payload_sha256=None,
                    alternate_path=alternate,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                ))
                continue

    document = _receipt_document(receipts, planned_mutations=min(len(mutations), max_mutations), credential_available=credential_available)
    destination = Path(receipt_path) if receipt_path is not None else state / "credential_bound_mutation_receipts.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {k: v for k, v in document.items() if k != "receipts"} | {"receipt_path": str(destination)}
