from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import discovery_external_action as action_module
from engine.credential_bound_mutation_runtime import (
    ConfiguredCredentialMutationRuntime,
    CredentialBoundMutationError,
)
from engine.discovery_capability_leases import DiscoveryCapabilityLease


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(repo: Path, host: str = "owner.example") -> None:
    _write(
        repo / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "host": host,
                    "base_url": f"https://{host}",
                    "owner_authorization": "explicit",
                }
            ]
        },
    )


def _policy(host: str = "owner.example", *, two_grants: bool = True) -> dict:
    grants = [
        {
            "grant_id": "synthetic-primary",
            "provider": "synthetic-test",
            "env_var": "SYNTHETIC_PRIMARY_TOKEN",
            "allowed_scopes": ["synthetic:write"],
            "allowed_methods": ["POST", "PUT", "PATCH"],
            "credential_scope": "service_bearer",
            "max_ttl_seconds": 300,
            "header_name": "Authorization",
            "header_scheme": "Bearer",
        }
    ]
    if two_grants:
        grants.append(
            {
                "grant_id": "synthetic-secondary",
                "provider": "synthetic-test",
                "env_var": "SYNTHETIC_SECONDARY_TOKEN",
                "allowed_scopes": ["synthetic:write"],
                "allowed_methods": ["POST", "PUT", "PATCH"],
                "credential_scope": "service_bearer",
                "max_ttl_seconds": 300,
                "header_name": "Authorization",
                "header_scheme": "Bearer",
            }
        )
    return {
        "schema": "meta-discovery-policy/test",
        "action_profiles": {
            host: {
                "owner_authorization": "explicit",
                "inherit_to_descendants": False,
                "capabilities": ["mutation", "credentialed_action"],
                "credential_scope": "service_bearer",
                "credential_grants": grants,
                "external_actions": {
                    "credentialed_action": [
                        {
                            "id": "credentialed-patch",
                            "method": "PATCH",
                            "path": "/records/current",
                            "alternate_paths": ["/records/current-alt"],
                            "content_type": "application/json",
                            "body": "{\"synthetic\":true,\"value\":1}",
                            "requires_credential": True,
                            "credential_grant_ids": ["synthetic-primary", "synthetic-secondary"],
                            "required_scopes": ["synthetic:write"],
                            "credential_ttl_seconds": 300,
                            "payload_mode": "ai_candidate_or_meta_synthesis",
                        }
                    ]
                },
            }
        },
    }


def _lease(now: int, host: str = "owner.example", *, inherited: bool = False) -> DiscoveryCapabilityLease:
    return DiscoveryCapabilityLease(
        lease_id="authority-lease-1",
        target=host,
        url=f"https://{host}/",
        authorization_reference="canonical:explicit-owner-test-host",
        authorization_basis="explicit_owner_authorized_target",
        capability_authorization_profile=host,
        capability_inherited_from_owner_root=inherited,
        capabilities=("mutation", "credentialed_action"),
        credential_scope="service_bearer",
        shared_with=("META", "X", "SENJU"),
        issued_at=now - 10,
        expires_at=now + 3600,
        source_action_fingerprint="abc123",
        status="active",
    )


def _lease_dict(now: int, host: str = "owner.example") -> dict:
    lease = _lease(now, host)
    return {
        "lease_id": lease.lease_id,
        "target": lease.target,
        "url": lease.url,
        "authorization_reference": lease.authorization_reference,
        "authorization_basis": lease.authorization_basis,
        "capability_authorization_profile": lease.capability_authorization_profile,
        "capability_inherited_from_owner_root": lease.capability_inherited_from_owner_root,
        "capabilities": list(lease.capabilities),
        "credential_scope": lease.credential_scope,
        "shared_with": list(lease.shared_with),
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
        "source_action_fingerprint": lease.source_action_fingerprint,
        "status": lease.status,
    }


def _action() -> dict:
    return {
        "id": "credentialed-patch",
        "method": "PATCH",
        "path": "/records/current",
        "alternate_paths": ["/records/current-alt"],
        "content_type": "application/json",
        "body": "{\"synthetic\":true,\"value\":1}",
        "requires_credential": True,
        "credential_grant_ids": ["synthetic-primary", "synthetic-secondary"],
        "required_scopes": ["synthetic:write"],
        "credential_ttl_seconds": 300,
        "payload_mode": "ai_candidate_or_meta_synthesis",
    }


def test_configured_grant_discovery_never_scans_undeclared_environment(tmp_path: Path) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"UNDECLARED_SECRET": "must-not-be-discovered"},
        now=now,
    )

    assert runtime.discover_configured_grants(_lease(now), _action()) == []
    with pytest.raises(CredentialBoundMutationError):
        runtime.headers_for(_lease(now), _action())


def test_credential_lease_binding_and_inheritance_never_persist_raw_secret(tmp_path: Path) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    secret = "runtime-only-super-test-value"
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"SYNTHETIC_PRIMARY_TOKEN": secret},
        now=now,
    )

    headers1 = runtime.headers_for(_lease(now), _action())
    use1 = runtime.current_use("credentialed-patch")
    action2 = {
        **_action(),
        "id": "credentialed-patch-second",
        "credential_ttl_seconds": 120,
    }
    headers2 = runtime.headers_for(_lease(now), action2)
    use2 = runtime.current_use("credentialed-patch-second")
    runtime.flush()

    assert headers1["Authorization"] == f"Bearer {secret}"
    assert headers2["Authorization"] == f"Bearer {secret}"
    assert use1 is not None and use2 is not None
    assert use2["strategy"] == "same_or_narrower_inheritance"
    assert use2["parent_lease_id"] == use1["lease_id"]
    persisted = (
        (state / "credential_bound_mutation_runtime.json").read_text()
        + (state / "credential_bound_mutation_learning.json").read_text()
        + (state / "credential_bound_mutation_events.ndjson").read_text()
    )
    assert secret not in persisted
    assert "env://" not in persisted


def test_ai_payload_candidate_must_be_exact_host_action_and_synthetic(tmp_path: Path) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    _write(
        state / "ai_mutation_payload_candidates.json",
        {
            "schema": "meta-ai-mutation-payload-candidates/v1",
            "candidates": [
                {
                    "producer": "META",
                    "host": "other.example",
                    "action_id": "credentialed-patch",
                    "content_type": "application/json",
                    "body": "{\"synthetic\":true,\"wrong\":true}",
                },
                {
                    "producer": "META",
                    "host": "owner.example",
                    "action_id": "credentialed-patch",
                    "content_type": "application/json",
                    "body": "{\"synthetic\":true,\"from_ai\":true}",
                },
            ],
        },
    )
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"SYNTHETIC_PRIMARY_TOKEN": "test"},
        now=now,
    )

    resolved = runtime.resolve_payload(_lease(now), _action())
    assert resolved.source == "validated_ai_candidate"
    assert json.loads(resolved.body.decode("utf-8")) == {"synthetic": True, "from_ai": True}


def test_inherited_descendant_lease_cannot_bind_credentials(tmp_path: Path) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"SYNTHETIC_PRIMARY_TOKEN": "test"},
        now=now,
    )

    with pytest.raises(CredentialBoundMutationError, match="inherited"):
        runtime.headers_for(_lease(now, inherited=True), _action())


def test_predeclared_same_host_alternate_path_after_404(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease_dict(now)]},
    )

    calls: list[dict] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            calls.append({"url": url, "method": method, "headers": dict(headers or {})})
            status = 404 if len(calls) == 1 else 200
            return SimpleNamespace(
                body=b"ok",
                receipt=SimpleNamespace(
                    status=status,
                    final_url=url,
                    response_sha256="11" * 32,
                ),
            )

    monkeypatch.setattr(action_module, "ExternalContactClient", FakeClient)
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"SYNTHETIC_PRIMARY_TOKEN": "primary"},
        now=now,
    )
    result = action_module.run_discovery_external_actions(
        state,
        repo_root=repo,
        credential_headers_resolver=runtime,
        payload_resolver=runtime.resolve_payload,
    )

    assert result["attempted"] == 1
    assert result["transport_attempts"] == 2
    assert result["succeeded"] == 1
    assert result["alternate_path_successes"] == 1
    assert [call["url"] for call in calls] == [
        "https://owner.example/records/current",
        "https://owner.example/records/current-alt",
    ]
    assert {call["method"] for call in calls} == {"PATCH"}
    receipt = result["receipts"][0]
    assert receipt["alternate_path_used"] is True
    assert receipt["contract"]["same_host_only"] is True
    assert receipt["contract"]["authority_expansion_allowed"] is False


def test_401_uses_next_preprovisioned_credential_on_same_path(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=True))
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease_dict(now)]},
    )

    calls: list[dict] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            header = dict(headers or {}).get("Authorization")
            calls.append({"url": url, "method": method, "authorization": header})
            status = 401 if header == "Bearer primary" else 200
            return SimpleNamespace(
                body=b"ok",
                receipt=SimpleNamespace(
                    status=status,
                    final_url=url,
                    response_sha256="22" * 32,
                ),
            )

    monkeypatch.setattr(action_module, "ExternalContactClient", FakeClient)
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={
            "SYNTHETIC_PRIMARY_TOKEN": "primary",
            "SYNTHETIC_SECONDARY_TOKEN": "secondary",
        },
        now=now,
    )
    result = action_module.run_discovery_external_actions(
        state,
        repo_root=repo,
        credential_headers_resolver=runtime,
        payload_resolver=runtime.resolve_payload,
    )

    assert result["attempted"] == 1
    assert result["transport_attempts"] == 2
    assert result["succeeded"] == 1
    assert result["credential_failover_successes"] == 1
    assert [call["url"] for call in calls] == [
        "https://owner.example/records/current",
        "https://owner.example/records/current",
    ]
    assert [call["authorization"] for call in calls] == [
        "Bearer primary",
        "Bearer secondary",
    ]
    receipt = result["receipts"][0]
    assert receipt["credential_failover_used"] is True
    assert receipt["alternate_path_used"] is False


def test_401_without_alternate_credential_does_not_probe_alternate_path(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(two_grants=False))
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease_dict(now)]},
    )

    calls: list[str] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            calls.append(url)
            return SimpleNamespace(
                body=b"denied",
                receipt=SimpleNamespace(
                    status=401,
                    final_url=url,
                    response_sha256="33" * 32,
                ),
            )

    monkeypatch.setattr(action_module, "ExternalContactClient", FakeClient)
    runtime = ConfiguredCredentialMutationRuntime(
        state,
        repo_root=repo,
        environ={"SYNTHETIC_PRIMARY_TOKEN": "primary"},
        now=now,
    )
    result = action_module.run_discovery_external_actions(
        state,
        repo_root=repo,
        credential_headers_resolver=runtime,
        payload_resolver=runtime.resolve_payload,
    )

    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert calls == ["https://owner.example/records/current"]
    receipt = result["receipts"][0]
    assert receipt["classification"] == "credential_permission_failure"
    assert receipt["alternate_path_used"] is False
