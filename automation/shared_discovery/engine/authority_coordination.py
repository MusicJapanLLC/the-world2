"""Cross-loop authority coordination without authority widening.

This module connects discovery capability leases to the downstream authority,
delegation, credential-possession, worker, persistence/recovery, and denial-feedback
loops through one immutable authority context.

It deliberately does not grant authority, fetch credentials, execute network actions,
or turn a denial into permission. The live discovery capability lease remains the source
of authority. Every downstream handoff must carry the same authority or a strict subset.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

COORDINATION_SCHEMA = "meta-authority-coordination-ledger/v1"
CONTEXT_SCHEMA = "meta-authority-context/v1"
HANDOFF_SCHEMA = "meta-authority-handoff/v1"
RECEIPT_SCHEMA = "meta-authority-stage-receipt/v1"

SUPPORTED_CAPABILITIES = frozenset(
    {"scan", "probe", "write", "mutation", "credentialed_action"}
)
HIGH_IMPACT_CAPABILITIES = frozenset({"write", "mutation", "credentialed_action"})

PIPELINE_STAGES = (
    "discovery",
    "capability_inheritance",
    "distributed_authority",
    "standing_delegation",
    "credential_possession",
    "worker_fleet",
    "persistence_recovery",
    "denial_learning",
)

BOUNDARY_DENIALS = frozenset(
    {
        "AUTHORITY_DENIED",
        "POLICY_DENIED",
        "OUT_OF_SCOPE",
        "CREDENTIAL_DENIED",
        "PRIVATE_NETWORK_DENIED",
        "SECURITY_STOP",
    }
)
SAME_CONTEXT_RETRY_DENIALS = frozenset({"NETWORK_DENIED", "TRANSIENT_FAILURE"})


class AuthorityCoordinationError(RuntimeError):
    """Raised when a handoff attempts to widen or corrupt an authority context."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object, *, prefix: str = "") -> str:
    payload = (prefix + _canonical_json(value)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_host(value: object) -> str:
    raw = str(value).strip().lower().rstrip(".")
    if not raw or "*" in raw or any(ch in raw for ch in "/?#@"):
        raise AuthorityCoordinationError(f"invalid exact host: {value!r}")
    try:
        return raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise AuthorityCoordinationError(f"invalid exact host: {value!r}") from exc


def _normalize_https_url(value: object) -> tuple[str, str]:
    raw = str(value).strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise AuthorityCoordinationError("invalid URL") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise AuthorityCoordinationError("authority context requires an exact HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise AuthorityCoordinationError("credentials in URL authority are forbidden")
    if port not in (None, 443):
        raise AuthorityCoordinationError("non-default HTTPS port is outside this protocol")
    host = _normalize_host(parsed.hostname)
    url = urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    return url, host


def _capabilities(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item).strip().lower()
                for item in values
                if str(item).strip().lower() in SUPPORTED_CAPABILITIES
            }
        )
    )


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


@dataclass(frozen=True)
class AuthorityContext:
    schema: str
    context_id: str
    lineage_id: str
    parent_authority_hash: str | None
    authority_hash: str
    idempotency_key: str
    target: str
    url: str
    authorization_reference: str
    authorization_basis: str | None
    capability_authorization_profile: str | None
    capability_inherited_from_owner_root: bool
    capabilities: tuple[str, ...]
    credential_scope: str
    shared_with: tuple[str, ...]
    source_lease_id: str
    source_action_fingerprint: str
    issued_at: int
    expires_at: int

    def is_active(self, *, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else int(now)
        return current < self.expires_at

    def allows(self, capability: str) -> bool:
        return str(capability).strip().lower() in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class StageReceipt:
    schema: str
    context_id: str
    lineage_id: str
    stage: str
    outcome: str
    authority_hash: str
    capabilities: tuple[str, ...]
    credential_scope: str
    recorded_at: int
    details: Mapping[str, object] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def context_from_lease(raw: Mapping[str, Any], *, now: int | None = None) -> AuthorityContext:
    """Convert one live discovery lease into an immutable cross-loop context.

    The conversion is intentionally one-way: this function may remove invalid authority,
    but it never invents capabilities, credential scopes, or authorization references.
    """
    current = int(time.time()) if now is None else int(now)
    if str(raw.get("status", "active")) != "active":
        raise AuthorityCoordinationError("source discovery lease is not active")

    target = _normalize_host(raw.get("target", ""))
    url, url_host = _normalize_https_url(raw.get("url", ""))
    if url_host != target:
        raise AuthorityCoordinationError("source lease target and URL host differ")

    try:
        issued_at = int(raw.get("issued_at", 0))
        expires_at = int(raw.get("expires_at", 0))
    except (TypeError, ValueError) as exc:
        raise AuthorityCoordinationError("invalid source lease timestamps") from exc
    if expires_at <= current:
        raise AuthorityCoordinationError("source discovery lease is expired")

    authorization_reference = str(raw.get("authorization_reference", "")).strip()
    source_lease_id = str(raw.get("lease_id", "")).strip()
    fingerprint = str(raw.get("source_action_fingerprint", "")).strip()
    if not authorization_reference or not source_lease_id or not fingerprint:
        raise AuthorityCoordinationError("source lease is missing authority lineage fields")

    capabilities = _capabilities(raw.get("capabilities", ()))
    if not capabilities:
        raise AuthorityCoordinationError("source lease has no supported capability")

    profile_raw = raw.get("capability_authorization_profile")
    profile = str(profile_raw).strip() if isinstance(profile_raw, str) and profile_raw.strip() else None
    credential_scope = str(raw.get("credential_scope", "none")).strip() or "none"

    # Defense in depth against stale/malformed artifacts. High-impact authority must
    # already have the explicit profile that the discovery-lease issuer requires.
    if set(capabilities) & HIGH_IMPACT_CAPABILITIES and profile is None:
        capabilities = tuple(cap for cap in capabilities if cap in {"scan", "probe"})
        credential_scope = "none"
    if "credentialed_action" in capabilities and credential_scope == "none":
        capabilities = tuple(cap for cap in capabilities if cap != "credentialed_action")
    if not capabilities:
        raise AuthorityCoordinationError("no capability remains after authority validation")
    if "credentialed_action" not in capabilities:
        credential_scope = "none"

    shared_with = tuple(
        sorted(
            {
                str(item).strip().upper()
                for item in raw.get("shared_with", ())
                if str(item).strip()
            }
        )
    )

    basis_raw = raw.get("authorization_basis")
    basis = str(basis_raw) if basis_raw is not None else None
    inherited = bool(raw.get("capability_inherited_from_owner_root", False))

    authority_material = {
        "target": target,
        "url": url,
        "authorization_reference": authorization_reference,
        "authorization_basis": basis,
        "capability_authorization_profile": profile,
        "capability_inherited_from_owner_root": inherited,
        "capabilities": capabilities,
        "credential_scope": credential_scope,
        "source_action_fingerprint": fingerprint,
        "expires_at": expires_at,
    }
    authority_hash = _digest(authority_material, prefix="authority-context-v1:")
    lineage_id = _digest(
        {"target": target, "authorization_reference": authorization_reference},
        prefix="authority-lineage-v1:",
    )[:24]
    context_id = _digest(
        {"lineage_id": lineage_id, "authority_hash": authority_hash, "source_lease_id": source_lease_id},
        prefix="authority-context-id-v1:",
    )[:32]
    idempotency_key = _digest(
        {"context_id": context_id, "source_action_fingerprint": fingerprint},
        prefix="authority-idempotency-v1:",
    )[:40]

    return AuthorityContext(
        schema=CONTEXT_SCHEMA,
        context_id=context_id,
        lineage_id=lineage_id,
        parent_authority_hash=None,
        authority_hash=authority_hash,
        idempotency_key=idempotency_key,
        target=target,
        url=url,
        authorization_reference=authorization_reference,
        authorization_basis=basis,
        capability_authorization_profile=profile,
        capability_inherited_from_owner_root=inherited,
        capabilities=capabilities,
        credential_scope=credential_scope,
        shared_with=shared_with,
        source_lease_id=source_lease_id,
        source_action_fingerprint=fingerprint,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def narrow_context(
    context: AuthorityContext,
    *,
    capabilities: Iterable[object],
    credential_scope: str | None = None,
) -> AuthorityContext:
    """Create a same-or-narrower child context for a downstream consumer."""
    requested = _capabilities(capabilities)
    if not requested:
        raise AuthorityCoordinationError("downstream context requires at least one capability")
    if not set(requested).issubset(set(context.capabilities)):
        raise AuthorityCoordinationError("downstream handoff attempted capability widening")

    scope = context.credential_scope if credential_scope is None else (str(credential_scope).strip() or "none")
    if context.credential_scope == "none" and scope != "none":
        raise AuthorityCoordinationError("downstream handoff attempted credential-scope widening")
    if context.credential_scope != "none" and scope not in {"none", context.credential_scope}:
        raise AuthorityCoordinationError("downstream credential scope must be identical or removed")
    if "credentialed_action" not in requested:
        scope = "none"

    material = {
        "parent_authority_hash": context.authority_hash,
        "target": context.target,
        "authorization_reference": context.authorization_reference,
        "capabilities": requested,
        "credential_scope": scope,
        "expires_at": context.expires_at,
    }
    child_hash = _digest(material, prefix="authority-child-v1:")
    child_id = _digest(
        {"lineage_id": context.lineage_id, "authority_hash": child_hash},
        prefix="authority-context-id-v1:",
    )[:32]
    child_key = _digest(
        {"parent": context.idempotency_key, "authority_hash": child_hash},
        prefix="authority-idempotency-v1:",
    )[:40]

    return dataclasses.replace(
        context,
        context_id=child_id,
        parent_authority_hash=context.authority_hash,
        authority_hash=child_hash,
        idempotency_key=child_key,
        capabilities=requested,
        credential_scope=scope,
    )


def build_handoff_plan(context: AuthorityContext) -> list[dict[str, Any]]:
    """Build deterministic handoffs for the PR #443..#460 pipeline.

    Handoffs are coordination records only. A ready handoff means the downstream system
    may evaluate/consume the context; it is not an execution approval by itself.
    """
    requires_credential = "credentialed_action" in context.capabilities
    stages = [
        ("distributed_authority", (), "ready"),
        ("standing_delegation", ("distributed_authority",), "waiting"),
        (
            "credential_possession",
            ("standing_delegation",),
            "waiting" if requires_credential else "not_required",
        ),
        (
            "worker_fleet",
            ("credential_possession",) if requires_credential else ("standing_delegation",),
            "waiting",
        ),
        ("persistence_recovery", ("worker_fleet",), "waiting"),
        ("denial_learning", (), "armed"),
    ]
    records: list[dict[str, Any]] = []
    for stage, depends_on, status in stages:
        handoff_id = _digest(
            {
                "context_id": context.context_id,
                "stage": stage,
                "authority_hash": context.authority_hash,
            },
            prefix="authority-handoff-v1:",
        )[:32]
        records.append(
            {
                "schema": HANDOFF_SCHEMA,
                "handoff_id": handoff_id,
                "context_id": context.context_id,
                "lineage_id": context.lineage_id,
                "stage": stage,
                "depends_on": list(depends_on),
                "status": status,
                "authority_hash": context.authority_hash,
                "idempotency_key": f"{context.idempotency_key}:{stage}",
                "target": context.target,
                "authorization_reference": context.authorization_reference,
                "capabilities": list(context.capabilities),
                "credential_scope": context.credential_scope,
                "expires_at": context.expires_at,
            }
        )
    return records


def stage_receipt(
    context: AuthorityContext,
    *,
    stage: str,
    outcome: str,
    effective_capabilities: Iterable[object] | None = None,
    credential_scope: str | None = None,
    details: Mapping[str, object] | None = None,
    now: int | None = None,
) -> StageReceipt:
    """Record a downstream result while enforcing the authority non-widening invariant."""
    stage_name = str(stage).strip().lower()
    if stage_name not in PIPELINE_STAGES:
        raise AuthorityCoordinationError(f"unknown pipeline stage: {stage!r}")
    if not context.is_active(now=now):
        raise AuthorityCoordinationError("cannot record an active handoff for an expired context")

    caps = context.capabilities if effective_capabilities is None else _capabilities(effective_capabilities)
    if not set(caps).issubset(set(context.capabilities)):
        raise AuthorityCoordinationError("stage receipt reports capability outside source context")

    scope = context.credential_scope if credential_scope is None else (str(credential_scope).strip() or "none")
    if context.credential_scope == "none" and scope != "none":
        raise AuthorityCoordinationError("stage receipt reports a new credential scope")
    if context.credential_scope != "none" and scope not in {"none", context.credential_scope}:
        raise AuthorityCoordinationError("stage receipt reports a different credential scope")
    if "credentialed_action" not in caps:
        scope = "none"

    safe_details: dict[str, object] = {}
    for key, value in (details or {}).items():
        name = str(key)[:80]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe_details[name] = value[:500] if isinstance(value, str) else value

    return StageReceipt(
        schema=RECEIPT_SCHEMA,
        context_id=context.context_id,
        lineage_id=context.lineage_id,
        stage=stage_name,
        outcome=str(outcome).strip().lower()[:80] or "unknown",
        authority_hash=context.authority_hash,
        capabilities=tuple(caps),
        credential_scope=scope,
        recorded_at=int(time.time()) if now is None else int(now),
        details=safe_details,
    )


def denial_policy(code: object) -> dict[str, object]:
    """Translate denial feedback into bounded recovery behavior.

    Boundary denials never authorize identity, route, host, method, credential, or scope
    changes. Only explicitly transient/network failures may be retried with the exact same
    authority context.
    """
    normalized = str(code).strip().upper() or "UNKNOWN"
    if normalized == "SECURITY_STOP":
        return {
            "denial": normalized,
            "terminal": True,
            "automatic_retry": False,
            "retry_mode": "none",
            "max_additional_attempts": 0,
        }
    if normalized in BOUNDARY_DENIALS:
        return {
            "denial": normalized,
            "terminal": False,
            "automatic_retry": False,
            "retry_mode": "external_policy_or_owner_change_required",
            "max_additional_attempts": 0,
        }
    if normalized in SAME_CONTEXT_RETRY_DENIALS:
        return {
            "denial": normalized,
            "terminal": False,
            "automatic_retry": True,
            "retry_mode": "exact_same_authority_context_only",
            "max_additional_attempts": 1,
        }
    return {
        "denial": normalized,
        "terminal": False,
        "automatic_retry": False,
        "retry_mode": "diagnose_only",
        "max_additional_attempts": 0,
    }


def _probe_receipts(state: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    payload = _load_json(state / "shared_probe_receipts.json", {})
    rows = payload.get("receipts", []) if isinstance(payload, dict) else []
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            host = _normalize_host(raw.get("host", ""))
        except AuthorityCoordinationError:
            continue
        reference = str(raw.get("authorization_reference", "")).strip()
        if host and reference:
            result[(host, reference)] = raw
    return result


def build_coordination_ledger(
    state_dir: str | Path,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Materialize active contexts and deterministic handoffs from live discovery leases."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)

    lease_payload = _load_json(state / "discovery_capability_leases.json", {})
    rows = lease_payload.get("leases", []) if isinstance(lease_payload, dict) else []
    if not isinstance(rows, list):
        rows = []

    contexts: list[AuthorityContext] = []
    rejected = 0
    seen: set[tuple[str, str, str]] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        try:
            context = context_from_lease(raw, now=current)
        except AuthorityCoordinationError:
            rejected += 1
            continue
        dedupe = (context.target, context.authorization_reference, context.source_action_fingerprint)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        contexts.append(context)

    contexts.sort(key=lambda item: (item.target, item.authorization_reference, item.context_id))
    probes = _probe_receipts(state)
    handoffs: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for context in contexts:
        handoffs.extend(build_handoff_plan(context))
        probe = probes.get((context.target, context.authorization_reference))
        if probe is not None:
            evidence.append(
                stage_receipt(
                    context,
                    stage="discovery",
                    outcome=str(probe.get("status", "unknown")),
                    effective_capabilities=("probe",) if "probe" in context.capabilities else context.capabilities,
                    credential_scope="none",
                    details={
                        "http_status": probe.get("http_status"),
                        "elapsed_ms": probe.get("elapsed_ms"),
                    },
                    now=current,
                ).to_dict()
            )

    payload = {
        "schema": COORDINATION_SCHEMA,
        "generated_at": current,
        "source": "live_discovery_capability_leases",
        "invariants": [
            "downstream_capabilities_must_be_same_or_narrower",
            "credential_scope_must_be_identical_or_removed",
            "denial_never_mints_authority",
            "recovery_reuses_authority_hash_and_idempotency_lineage",
            "raw_credentials_are_never_stored_in_coordination_state",
        ],
        "context_count": len(contexts),
        "rejected_source_lease_count": rejected,
        "contexts": [context.to_dict() for context in contexts],
        "handoffs": handoffs,
        "stage_evidence": evidence,
    }
    (state / "authority_coordination_ledger.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "context_count": len(contexts),
        "handoff_count": len(handoffs),
        "evidence_count": len(evidence),
        "rejected_source_lease_count": rejected,
    }
