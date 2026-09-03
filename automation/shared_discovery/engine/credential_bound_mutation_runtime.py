"""Credential-bound mutation runtime for explicitly owner-authorized synthetic test hosts.

This module intentionally closes a *bounded* execution loop:

    exact explicit Owner host
      + live discovery capability lease
      + pre-registered synthetic credential grant
      + short-lived credential lease
      + META-generated/validated synthetic payload
      + POST/PUT/PATCH
      + predeclared same-host fallback path

It does not discover raw secrets. Credential "discovery" means selecting metadata for
credential grants explicitly declared in the exact-host action profile and resolving only
the environment-variable names declared by those grants. It never scans environment
variables, files, logs, browsers, cloud metadata, repositories, or third-party systems.

Credential inheritance is same-or-narrower: a later use may exchange an active lease for
an equal/narrower child lease, but scopes, host, method, and credential authority never
expand. Raw credential values are used in memory only and are never written to state,
receipts, artifacts, or logs.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host
from .discovery_capability_leases import DiscoveryCapabilityLease

from senju.authority_factory import root_from_external_scope
from senju.credential_broker import (
    CredentialBroker,
    CredentialBrokerError,
    CredentialGrant,
)
from senju.external import ExternalAuthorityScope

RUNTIME_SCHEMA = "meta-credential-bound-mutation-runtime/v1"
LEARNING_SCHEMA = "meta-credential-bound-mutation-learning/v1"
EVENT_SCHEMA = "meta-credential-bound-mutation-event/v1"
AI_PAYLOAD_SCHEMA = "meta-ai-mutation-payload-candidates/v1"
ALLOWED_ACTORS = frozenset({"META", "X"})
ALLOWED_METHODS = frozenset({"POST", "PUT", "PATCH"})
ALLOWED_AI_PRODUCERS = frozenset({"META", "X", "SENJU"})
MAX_PAYLOAD_BYTES = 16 * 1024
MAX_CREDENTIAL_ATTEMPTS_PER_ACTION = 3


class CredentialBoundMutationError(RuntimeError):
    """Fail-closed error for credential-bound mutation setup or execution binding."""


@dataclass(frozen=True)
class CredentialUse:
    action_id: str
    grant_id: str
    lease_id: str
    parent_lease_id: str | None
    scopes: tuple[str, ...]
    header_name: str
    generation: int
    strategy: str


@dataclass(frozen=True)
class PayloadResolution:
    body: bytes | None
    source: str
    sha256: str | None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_event(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema": EVENT_SCHEMA, **dict(payload)}, ensure_ascii=False, sort_keys=True) + "\n")


def _exact_owner_hosts(repo_root: Path) -> set[str]:
    """Return only exact hosts explicitly named by the canonical owner target registry."""
    doc = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    targets = doc.get("targets", ()) if isinstance(doc, Mapping) else ()
    hosts: set[str] = set()
    if not isinstance(targets, list):
        return hosts
    for row in targets:
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


def _safe_header_name(value: object) -> str:
    name = str(value or "Authorization").strip()
    if not name or any(ch in name for ch in "\r\n:"):
        raise CredentialBoundMutationError("invalid credential header name")
    if name.lower() in {"host", "content-length", "transfer-encoding", "connection"}:
        raise CredentialBoundMutationError("credential header name is not allowed")
    return name


def _scopes(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item).strip() for item in value if str(item).strip())


def _synthetic_payload_ok(content_type: str, body: str) -> bool:
    lower = content_type.split(";", 1)[0].strip().lower()
    if lower == "application/json":
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return False
        return isinstance(parsed, Mapping) and parsed.get("synthetic") is True
    if lower == "application/x-www-form-urlencoded":
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        values = {str(v).strip().lower() for v in parsed.get("synthetic", [])}
        return bool(values & {"true", "1", "yes"})
    return False


class ConfiguredCredentialMutationRuntime:
    """Bind exact-host Authority leases to declared synthetic credentials and payloads."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        repo_root: str | Path,
        actor: str = "META",
        environ: Mapping[str, str] | None = None,
        now: int | None = None,
    ) -> None:
        actor = str(actor).strip().upper()
        if actor not in ALLOWED_ACTORS:
            raise CredentialBoundMutationError(f"unsupported credential actor: {actor}")
        self.state = Path(state_dir)
        self.repo_root = Path(repo_root)
        self.actor = actor
        self.environ = dict(os.environ if environ is None else environ)
        self.now = int(time.time()) if now is None else int(now)
        self.broker = CredentialBroker()
        self.owner_hosts = _exact_owner_hosts(self.repo_root)
        self.learning_path = self.state / "credential_bound_mutation_learning.json"
        self.events_path = self.state / "credential_bound_mutation_events.ndjson"
        self.learning = self._load_learning()
        self._registered: set[str] = set()
        self._active_lease_by_grant: dict[str, str] = {}
        self._attempted_grants_by_action: dict[str, set[str]] = {}
        self._current_use_by_action: dict[str, CredentialUse] = {}

    def _load_learning(self) -> dict[str, dict[str, int]]:
        doc = _load_json(self.learning_path, {})
        rows = doc.get("grants", {}) if isinstance(doc, Mapping) else {}
        out: dict[str, dict[str, int]] = {}
        if not isinstance(rows, Mapping):
            return out
        for grant_id, raw in rows.items():
            if not isinstance(raw, Mapping):
                continue
            try:
                out[str(grant_id)] = {
                    "successes": max(0, int(raw.get("successes", 0))),
                    "permission_failures": max(0, int(raw.get("permission_failures", 0))),
                }
            except (TypeError, ValueError):
                continue
        return out

    def _profile(self, lease: DiscoveryCapabilityLease) -> Mapping[str, Any]:
        if lease.target not in self.owner_hosts:
            raise CredentialBoundMutationError("credential mutation requires an exact canonical explicit-owner host")
        if lease.capability_inherited_from_owner_root:
            raise CredentialBoundMutationError("credential mutation may not use inherited descendant authority")
        if not lease.is_active(now=self.now):
            raise CredentialBoundMutationError("authority lease is not active")
        if "credentialed_action" not in lease.capabilities or lease.credential_scope == "none":
            raise CredentialBoundMutationError("live Authority lease does not include credentialed_action")

        policy = _load_json(self.state / "discovery_policy.json", {})
        profiles = policy.get("action_profiles", {}) if isinstance(policy, Mapping) else {}
        raw = profiles.get(lease.target) if isinstance(profiles, Mapping) else None
        if not isinstance(raw, Mapping) or raw.get("owner_authorization") != "explicit":
            raise CredentialBoundMutationError("exact-host explicit action profile is missing")
        if bool(raw.get("inherit_to_descendants", False)):
            # The profile may authorize ordinary descendants elsewhere, but this runtime
            # intentionally refuses credential inheritance semantics at that boundary.
            pass
        if str(raw.get("credential_scope") or "none").strip() != lease.credential_scope:
            raise CredentialBoundMutationError("profile and live lease credential scopes do not match")
        return raw

    def _grant_rows(self, lease: DiscoveryCapabilityLease, action: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        profile = self._profile(lease)
        rows = profile.get("credential_grants", ())
        if not isinstance(rows, list):
            return []
        requested_ids = {
            str(item).strip()
            for item in action.get("credential_grant_ids", [])
            if str(item).strip()
        }
        required_scopes = _scopes(action.get("required_scopes"))
        method = str(action.get("method") or "").strip().upper()
        if method not in ALLOWED_METHODS:
            raise CredentialBoundMutationError("credential-bound mutations are limited to POST/PUT/PATCH")
        if not required_scopes:
            raise CredentialBoundMutationError("credential-bound action requires explicit scopes")

        eligible: list[Mapping[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            grant_id = str(raw.get("grant_id") or "").strip()
            env_var = str(raw.get("env_var") or "").strip()
            if not grant_id or (requested_ids and grant_id not in requested_ids):
                continue
            if not env_var or not env_var.replace("_", "").isalnum() or env_var.upper() != env_var:
                continue
            # No environment scanning: only the exact configured name is consulted.
            if not self.environ.get(env_var):
                continue
            allowed_methods = {
                str(item).strip().upper()
                for item in raw.get("allowed_methods", [])
                if str(item).strip()
            }
            allowed_scopes = _scopes(raw.get("allowed_scopes"))
            if method not in allowed_methods or not required_scopes.issubset(allowed_scopes):
                continue
            if str(raw.get("credential_scope") or "service_bearer").strip() != lease.credential_scope:
                continue
            eligible.append(raw)

        def score(row: Mapping[str, Any]) -> tuple[int, int, str]:
            stats = self.learning.get(str(row.get("grant_id") or ""), {})
            successes = int(stats.get("successes", 0))
            failures = int(stats.get("permission_failures", 0))
            return (-successes, failures, str(row.get("grant_id") or ""))

        eligible.sort(key=score)
        return eligible

    def discover_configured_grants(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Return secret-free metadata for configured *and provisioned* exact-host grants."""
        out: list[dict[str, Any]] = []
        for row in self._grant_rows(lease, action):
            out.append(
                {
                    "grant_id": str(row.get("grant_id")),
                    "provider": str(row.get("provider")),
                    "allowed_scopes": sorted(_scopes(row.get("allowed_scopes"))),
                    "allowed_methods": sorted(
                        str(item).strip().upper()
                        for item in row.get("allowed_methods", [])
                        if str(item).strip()
                    ),
                    "credential_scope": str(row.get("credential_scope") or "service_bearer"),
                    "secret_material_exposed": False,
                }
            )
        return out

    def _register_grant(self, row: Mapping[str, Any]) -> None:
        grant_id = str(row.get("grant_id") or "").strip()
        if grant_id in self._registered:
            return
        max_ttl = max(30, min(int(row.get("max_ttl_seconds", 300)), 3600))
        self.broker.register_grant(
            CredentialGrant(
                grant_id=grant_id,
                provider=str(row.get("provider") or "synthetic-test").strip(),
                credential_ref=f"env://{str(row.get('env_var') or '').strip()}",
                allowed_scopes=_scopes(row.get("allowed_scopes")),
                required_authority_scope=str(row.get("credential_scope") or "service_bearer").strip(),
                max_ttl_seconds=max_ttl,
                exchangeable=True,
                delegable=False,
                description="Exact-host pre-provisioned synthetic test credential",
            )
        )
        self._registered.add(grant_id)

    def _authority(self, lease: DiscoveryCapabilityLease, action: Mapping[str, Any]):
        method = str(action.get("method") or "").strip().upper()
        scope = ExternalAuthorityScope(
            scope_id=f"credential-bound-mutation:{lease.target}",
            target_service="Explicit owner-authorized synthetic mutation",
            allow_hosts=frozenset({lease.target}),
            allowed_methods=frozenset({method}),
            allow_http=False,
            allow_delete=False,
            rate_limit_per_minute=30,
            timeout_seconds=8.0,
            max_request_bytes=MAX_PAYLOAD_BYTES,
            max_response_bytes=256 * 1024,
            retries=1,
            follow_redirects=False,
            credential_scope=lease.credential_scope,
            description="Exact-host credential-bound synthetic mutation runtime",
        )
        return root_from_external_scope(scope, delegation_depth=0)

    def _issue_for_row(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
        row: Mapping[str, Any],
    ) -> tuple[dict[str, str], CredentialUse]:
        self._register_grant(row)
        grant_id = str(row.get("grant_id") or "").strip()
        required_scopes = _scopes(action.get("required_scopes"))
        authority = self._authority(lease, action)
        requested_ttl = max(30, min(int(action.get("credential_ttl_seconds", 300)), 900))
        remaining_authority = max(0, int(lease.expires_at) - self.now)
        ttl = min(requested_ttl, remaining_authority, int(row.get("max_ttl_seconds", 300)))
        if ttl < 30:
            raise CredentialBoundMutationError("insufficient Authority lease lifetime for credential lease")

        parent_id = self._active_lease_by_grant.get(grant_id)
        strategy = "issue"
        credential_lease = None
        if parent_id:
            try:
                credential_lease = self.broker.exchange(
                    authority,
                    actor=self.actor,
                    parent_lease_id=parent_id,
                    scopes=required_scopes,
                    ttl_seconds=ttl,
                )
                strategy = "same_or_narrower_inheritance"
            except CredentialBrokerError:
                credential_lease = None
        if credential_lease is None:
            credential_lease = self.broker.issue(
                authority,
                actor=self.actor,
                grant_id=grant_id,
                scopes=required_scopes,
                ttl_seconds=ttl,
            )

        ref = self.broker.resolve_credential_ref(actor=self.actor, lease_id=credential_lease.lease_id)
        if not ref.startswith("env://"):
            raise CredentialBoundMutationError("only configured env:// credential references are supported")
        env_var = ref[len("env://") :]
        secret = self.environ.get(env_var, "")
        if not secret:
            raise CredentialBoundMutationError("configured credential is no longer provisioned")

        header_name = _safe_header_name(row.get("header_name", "Authorization"))
        scheme = str(row.get("header_scheme", "Bearer")).strip()
        header_value = f"{scheme} {secret}" if scheme else secret
        use = CredentialUse(
            action_id=str(action.get("id") or ""),
            grant_id=grant_id,
            lease_id=credential_lease.lease_id,
            parent_lease_id=credential_lease.parent_lease_id,
            scopes=tuple(sorted(required_scopes)),
            header_name=header_name,
            generation=credential_lease.generation,
            strategy=strategy,
        )
        self._active_lease_by_grant[grant_id] = credential_lease.lease_id
        self._current_use_by_action[use.action_id] = use
        self._attempted_grants_by_action.setdefault(use.action_id, set()).add(grant_id)
        _append_event(
            self.events_path,
            {
                "at": self.now,
                "event": "credential_lease_bound",
                "target": lease.target,
                "action_id": use.action_id,
                "grant_id": grant_id,
                "lease_id": use.lease_id,
                "parent_lease_id": use.parent_lease_id,
                "generation": use.generation,
                "strategy": strategy,
                "scopes": list(use.scopes),
                "secret_material_persisted": False,
            },
        )
        return {header_name: header_value}, use

    def headers_for(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
    ) -> Mapping[str, str]:
        action_id = str(action.get("id") or "").strip()
        attempted = self._attempted_grants_by_action.setdefault(action_id, set())
        rows = [
            row
            for row in self._grant_rows(lease, action)
            if str(row.get("grant_id") or "").strip() not in attempted
        ]
        if not rows:
            raise CredentialBoundMutationError("no provisioned pre-registered credential grant satisfies this action")
        headers, _ = self._issue_for_row(lease, action, rows[0])
        return headers

    def __call__(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
    ) -> Mapping[str, str]:
        return self.headers_for(lease, action)

    def next_headers(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
    ) -> Mapping[str, str] | None:
        """Try the next *pre-provisioned* grant; never scan for new credentials."""
        action_id = str(action.get("id") or "").strip()
        attempted = self._attempted_grants_by_action.setdefault(action_id, set())
        if len(attempted) >= MAX_CREDENTIAL_ATTEMPTS_PER_ACTION:
            return None
        rows = [
            row
            for row in self._grant_rows(lease, action)
            if str(row.get("grant_id") or "").strip() not in attempted
        ]
        if not rows:
            return None
        headers, _ = self._issue_for_row(lease, action, rows[0])
        return headers

    def current_use(self, action_id: str) -> dict[str, Any] | None:
        use = self._current_use_by_action.get(str(action_id))
        if use is None:
            return None
        return {
            "grant_id": use.grant_id,
            "lease_id": use.lease_id,
            "parent_lease_id": use.parent_lease_id,
            "scopes": list(use.scopes),
            "generation": use.generation,
            "strategy": use.strategy,
        }

    def report_http_status(self, action_id: str, status: int) -> None:
        use = self._current_use_by_action.get(str(action_id))
        if use is None:
            return
        stats = self.learning.setdefault(use.grant_id, {"successes": 0, "permission_failures": 0})
        if 200 <= int(status) < 300:
            stats["successes"] = int(stats.get("successes", 0)) + 1
        elif int(status) in {401, 403}:
            stats["permission_failures"] = int(stats.get("permission_failures", 0)) + 1
        self.flush()

    def _ai_candidate(self, lease: DiscoveryCapabilityLease, action: Mapping[str, Any]) -> str | None:
        doc = _load_json(self.state / "ai_mutation_payload_candidates.json", {})
        if not isinstance(doc, Mapping) or str(doc.get("schema") or AI_PAYLOAD_SCHEMA) != AI_PAYLOAD_SCHEMA:
            return None
        rows = doc.get("candidates", ())
        if not isinstance(rows, list):
            return None
        action_id = str(action.get("id") or "")
        content_type = str(action.get("content_type") or "application/json")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("producer") or "").strip().upper() not in ALLOWED_AI_PRODUCERS:
                continue
            try:
                host = _normalize_host(str(row.get("host") or ""))
            except ValueError:
                continue
            if host != lease.target or str(row.get("action_id") or "") != action_id:
                continue
            if str(row.get("content_type") or "").split(";", 1)[0].strip().lower() != content_type.split(";", 1)[0].strip().lower():
                continue
            body = row.get("body")
            if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                continue
            if not _synthetic_payload_ok(content_type, body):
                continue
            return body
        return None

    def resolve_payload(
        self,
        lease: DiscoveryCapabilityLease,
        action: Mapping[str, Any],
    ) -> PayloadResolution:
        """Use a validated META/X/SENJU payload candidate or synthesize a safe synthetic payload."""
        self._profile(lease)
        content_type = str(action.get("content_type") or "application/json")
        candidate = self._ai_candidate(lease, action)
        if candidate is not None:
            raw = candidate.encode("utf-8")
            return PayloadResolution(raw, "validated_ai_candidate", hashlib.sha256(raw).hexdigest())

        base = action.get("body")
        if base is not None and not isinstance(base, str):
            raise CredentialBoundMutationError("declared mutation body must be a string or null")
        nonce = hashlib.sha256(
            f"{lease.lease_id}:{action.get('id')}:{self.now}".encode("utf-8")
        ).hexdigest()[:16]
        lower = content_type.split(";", 1)[0].strip().lower()
        if lower == "application/json":
            try:
                parsed = json.loads(base or "{}")
            except json.JSONDecodeError as exc:
                raise CredentialBoundMutationError("declared JSON payload template is invalid") from exc
            if not isinstance(parsed, dict):
                raise CredentialBoundMutationError("JSON payload template must be an object")
            parsed["synthetic"] = True
            parsed["_meta"] = {
                "producer": self.actor,
                "mode": "credential_bound_mutation",
                "action_id": str(action.get("id") or ""),
                "nonce": nonce,
                "generated_at": self.now,
            }
            text = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif lower == "application/x-www-form-urlencoded":
            pairs = urllib.parse.parse_qsl(base or "", keep_blank_values=True)
            data = {str(key): str(value) for key, value in pairs}
            data.update(
                {
                    "synthetic": "true",
                    "source": self.actor.lower() + "-credential-bound-mutation",
                    "action_id": str(action.get("id") or ""),
                    "nonce": nonce,
                }
            )
            text = urllib.parse.urlencode(data)
        else:
            raise CredentialBoundMutationError("credential-bound AI payload synthesis supports JSON or form data only")

        raw = text.encode("utf-8")
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise CredentialBoundMutationError("synthesized payload exceeds request limit")
        return PayloadResolution(raw, "meta_synthetic_synthesis", hashlib.sha256(raw).hexdigest())

    def flush(self) -> None:
        _write_json(
            self.learning_path,
            {
                "schema": LEARNING_SCHEMA,
                "generated_at": int(time.time()),
                "grants": self.learning,
                "raw_credentials_persisted": False,
                "credential_discovery_mode": "configured_grant_metadata_only",
            },
        )
        _write_json(
            self.state / "credential_bound_mutation_runtime.json",
            {
                "schema": RUNTIME_SCHEMA,
                "generated_at": int(time.time()),
                "actor": self.actor,
                "exact_owner_hosts": sorted(self.owner_hosts),
                "registered_grant_ids": sorted(self._registered),
                "active_action_uses": {
                    action_id: self.current_use(action_id)
                    for action_id in sorted(self._current_use_by_action)
                },
                "raw_credentials_persisted": False,
                "environment_scanning": False,
                "filesystem_secret_scanning": False,
                "cross_host_credential_inheritance": False,
                "same_or_narrower_credential_lease_inheritance": True,
            },
        )
