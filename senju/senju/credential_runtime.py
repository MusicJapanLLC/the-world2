"""Runtime wiring for META/X credential permission recovery.

This module connects the existing CredentialSelfTuner and CredentialRecoveryLoop to
explicitly provisioned runtime credentials. It is intentionally *not* a credential
escalation mechanism: it can only select among credentials that an operator already
injected into the process and whose capability metadata is declared in configuration.

Runtime grants contain environment-variable *names*, never secret values. A selected
secret is resolved only in memory for an immediate retry and is never written to tuning
history, SecretMemory, logs, artifacts, or state files.
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .authority_factory import AuthorityProfile, root_from_external_scope
from .credential_broker import CredentialBroker, CredentialGrant, CredentialLease
from .credential_recovery_loop import CredentialRecoveryLoop, RecoveryLoopResult
from .credential_self_tuner import (
    CredentialSelfTuner,
    CredentialTuneResult,
    PermissionNeed,
    TuneOutcome,
)
from .external import ExternalAuthorityScope
from .secret_memory import SecretMemoryIndex, assert_no_raw_secret_fields


class CredentialRuntimeError(RuntimeError):
    """Raised when runtime credential configuration is invalid or cannot be resolved."""


DEFAULT_GITHUB_ACTIONS_SCOPES = frozenset(
    {
        "metadata:read",
        "contents:write",
        "pull_requests:write",
        "actions:write",
        "issues:write",
    }
)


@dataclass(frozen=True)
class RuntimeGrant:
    grant_id: str
    provider: str
    env_var: str
    allowed_scopes: frozenset[str]
    required_authority_scope: str = "service_bearer"
    max_ttl_seconds: int = 900

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimeGrant":
        assert_no_raw_secret_fields(value)
        allowed_keys = {
            "grant_id",
            "provider",
            "env_var",
            "allowed_scopes",
            "required_authority_scope",
            "max_ttl_seconds",
        }
        unknown = set(value) - allowed_keys
        if unknown:
            raise CredentialRuntimeError(f"unsupported runtime grant fields: {sorted(unknown)}")
        try:
            grant = cls(
                grant_id=str(value["grant_id"]).strip(),
                provider=str(value["provider"]).strip().lower(),
                env_var=str(value["env_var"]).strip(),
                allowed_scopes=frozenset(str(v).strip() for v in value["allowed_scopes"] if str(v).strip()),
                required_authority_scope=str(value.get("required_authority_scope", "service_bearer")).strip(),
                max_ttl_seconds=int(value.get("max_ttl_seconds", 900)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CredentialRuntimeError("invalid runtime credential grant") from exc
        if not grant.grant_id or not grant.provider or not grant.env_var or not grant.allowed_scopes:
            raise CredentialRuntimeError("runtime grant requires grant_id/provider/env_var/allowed_scopes")
        if not grant.env_var.replace("_", "").isalnum() or grant.env_var.upper() != grant.env_var:
            raise CredentialRuntimeError("env_var must be an uppercase environment-variable name")
        return grant


@dataclass
class CredentialRecoveryRuntime:
    """Production-facing least-privilege credential recovery adapter."""

    actor: str
    authority: AuthorityProfile
    broker: CredentialBroker
    tuner: CredentialSelfTuner
    recovery_loop: CredentialRecoveryLoop
    state_dir: Path | None = None
    current_lease_by_operation: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_environment(
        cls,
        *,
        actor: str = "META",
        environ: Mapping[str, str] | None = None,
        state_dir: Path | None = None,
    ) -> "CredentialRecoveryRuntime":
        env = dict(os.environ if environ is None else environ)
        grants: list[RuntimeGrant] = []

        if env.get("GITHUB_TOKEN"):
            grants.append(
                RuntimeGrant(
                    grant_id="github-actions-current",
                    provider="github",
                    env_var="GITHUB_TOKEN",
                    allowed_scopes=DEFAULT_GITHUB_ACTIONS_SCOPES,
                    required_authority_scope="service_bearer",
                    max_ttl_seconds=900,
                )
            )

        raw_extra = env.get("SENJU_CREDENTIAL_GRANTS_JSON", "").strip()
        if raw_extra:
            try:
                parsed = json.loads(raw_extra)
            except json.JSONDecodeError as exc:
                raise CredentialRuntimeError("SENJU_CREDENTIAL_GRANTS_JSON is not valid JSON") from exc
            if not isinstance(parsed, list):
                raise CredentialRuntimeError("SENJU_CREDENTIAL_GRANTS_JSON must be a JSON list")
            for item in parsed:
                if not isinstance(item, Mapping):
                    raise CredentialRuntimeError("each runtime credential grant must be an object")
                grant = RuntimeGrant.from_mapping(item)
                if env.get(grant.env_var):
                    grants.append(grant)

        by_id: dict[str, RuntimeGrant] = {grant.grant_id: grant for grant in grants}
        grants = [by_id[key] for key in sorted(by_id)]

        broker = CredentialBroker()
        for grant in grants:
            broker.register_grant(
                CredentialGrant(
                    grant_id=grant.grant_id,
                    provider=grant.provider,
                    credential_ref=f"env://{grant.env_var}",
                    allowed_scopes=grant.allowed_scopes,
                    required_authority_scope=grant.required_authority_scope,
                    max_ttl_seconds=grant.max_ttl_seconds,
                    exchangeable=True,
                    delegable=True,
                    description="Explicitly provisioned runtime credential",
                )
            )

        credential_scope = "service_bearer" if any(
            grant.required_authority_scope == "service_bearer" for grant in grants
        ) else ("public_token" if grants else "none")
        scope = ExternalAuthorityScope(
            scope_id="runtime_preapproved_credentials",
            target_service="Pre-approved runtime credential selection",
            allow_hosts=frozenset({"api.github.com"}),
            allowed_methods=frozenset({"GET", "HEAD", "POST", "PUT", "PATCH"}),
            allow_delete=False,
            rate_limit_per_minute=60,
            timeout_seconds=15.0,
            max_request_bytes=256 * 1024,
            max_response_bytes=4 * 1024 * 1024,
            retries=1,
            follow_redirects=False,
            credential_scope=credential_scope,
            description="Credential ceiling backed only by secrets already provisioned to this runtime",
        )
        authority = root_from_external_scope(scope, delegation_depth=0)
        memory = SecretMemoryIndex()
        tuner = CredentialSelfTuner(broker=broker, secret_memory=memory)
        recovery_loop = CredentialRecoveryLoop(broker=broker, secret_memory=memory)

        # Learn across workflow/process restarts. Only secret-free grant ids and counters
        # are restored, and counters for grants no longer provisioned are discarded.
        if state_dir is not None:
            learning_path = Path(state_dir) / "credential_recovery_learning.json"
            if learning_path.exists():
                try:
                    learned = json.loads(learning_path.read_text(encoding="utf-8"))
                    valid_ids = set(broker.grants)
                    recovery_loop.grant_successes = {
                        str(key): max(0, int(value))
                        for key, value in dict(learned.get("grant_successes", {})).items()
                        if str(key) in valid_ids
                    }
                    recovery_loop.grant_failures = {
                        str(key): max(0, int(value))
                        for key, value in dict(learned.get("grant_failures", {})).items()
                        if str(key) in valid_ids
                    }
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    # Corrupt/stale learning state must never block runtime startup.
                    recovery_loop.grant_successes = {}
                    recovery_loop.grant_failures = {}

        return cls(
            actor=actor,
            authority=authority,
            broker=broker,
            tuner=tuner,
            recovery_loop=recovery_loop,
            state_dir=state_dir,
        )

    def recover(
        self,
        *,
        provider: str,
        required_scopes: Iterable[str],
        operation: str,
        resource: str = "",
        error_code: str = "permission_denied",
        ttl_seconds: int = 300,
    ) -> CredentialTuneResult:
        current = self.current_lease_by_operation.get(operation)
        result = self.tuner.recover_permission_failure(
            self.authority,
            actor=self.actor,
            need=PermissionNeed(
                provider=provider,
                required_scopes=frozenset(required_scopes),
                operation=operation,
                resource=resource,
                error_code=error_code,
                ttl_seconds=ttl_seconds,
            ),
            current_lease_id=current,
        )
        if result.recovered and result.lease_id:
            self.current_lease_by_operation[operation] = result.lease_id
        self._persist_secret_free_state()
        return result

    def recover_operation(
        self,
        *,
        provider: str,
        required_scopes: Iterable[str],
        operation: str,
        resource: str,
        error_code: str,
        attempt_with_secret: Callable[[str], Mapping[str, Any]],
        ttl_seconds: int = 300,
    ) -> tuple[RecoveryLoopResult, Mapping[str, Any] | None]:
        last_response: Mapping[str, Any] | None = None
        need = PermissionNeed(
            provider=provider,
            required_scopes=frozenset(required_scopes),
            operation=operation,
            resource=resource,
            error_code=error_code,
            ttl_seconds=ttl_seconds,
        )

        def attempt(lease: CredentialLease) -> bool:
            nonlocal last_response
            secret = self.resolve_lease_secret(lease.lease_id)
            last_response = attempt_with_secret(secret)
            return not is_permission_error(last_response)

        result = self.recovery_loop.run(
            self.authority,
            actor=self.actor,
            need=need,
            attempt_operation=attempt,
        )
        if result.recovered and result.lease_id:
            self.current_lease_by_operation[operation] = result.lease_id
        self._persist_secret_free_state()
        return result, last_response

    def resolve_lease_secret(self, lease_id: str) -> str:
        ref = self.broker.resolve_credential_ref(actor=self.actor, lease_id=lease_id)
        if not ref.startswith("env://"):
            raise CredentialRuntimeError("runtime only resolves env:// credential references")
        env_var = ref[len("env://") :]
        value = os.environ.get(env_var, "")
        if not value:
            raise CredentialRuntimeError(f"selected credential environment variable is unavailable: {env_var}")
        return value

    def resolve_selected_secret(self, result: CredentialTuneResult) -> str | None:
        if result.outcome is not TuneOutcome.RECOVERED or not result.lease_id:
            return None
        return self.resolve_lease_secret(result.lease_id)

    def result_record(self, result: CredentialTuneResult) -> dict[str, Any]:
        data = dataclasses.asdict(result)
        data["outcome"] = result.outcome.value
        data["strategy"] = result.strategy.value
        assert_no_raw_secret_fields(data)
        return data

    def loop_result_record(self, result: RecoveryLoopResult) -> dict[str, Any]:
        data = dataclasses.asdict(result)
        assert_no_raw_secret_fields(data)
        return data

    def _persist_secret_free_state(self) -> None:
        if self.state_dir is None:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        history_path = self.state_dir / "credential_tuning_history.json"
        memory_path = self.state_dir / "credential_secret_memory.json"
        learning_path = self.state_dir / "credential_recovery_learning.json"
        history_path.write_text(
            json.dumps(self.tuner.history(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        memory_path.write_text(
            json.dumps(self.tuner.secret_memory.export_all() if self.tuner.secret_memory else {}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        learning_path.write_text(
            json.dumps(self.recovery_loop.learning_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def is_permission_error(result: Mapping[str, Any]) -> bool:
    code = result.get("_error")
    return str(code) in {"401", "403"}
