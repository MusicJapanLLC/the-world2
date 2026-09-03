from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from engine import discovery_external_action as module


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lease(now: int, *, credentialed: bool = False) -> dict:
    capabilities = ["scan", "probe", "write", "mutation"]
    credential_scope = "none"
    if credentialed:
        capabilities.append("credentialed_action")
        credential_scope = "service_bearer"
    return {
        "lease_id": "lease-1",
        "target": "owner.example",
        "url": "https://owner.example/",
        "authorization_reference": "canonical:owner",
        "authorization_basis": "trusted_root",
        "capability_authorization_profile": "owner.example",
        "capability_inherited_from_owner_root": False,
        "capabilities": capabilities,
        "credential_scope": credential_scope,
        "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
        "issued_at": now - 10,
        "expires_at": now + 3600,
        "source_action_fingerprint": "abc123",
        "status": "active",
    }


def _policy(*, credentialed_patch: bool = False) -> dict:
    return {
        "schema": "meta-discovery-policy/v3",
        "action_profiles": {
            "owner.example": {
                "owner_authorization": "explicit",
                "capabilities": ["scan", "probe", "write", "mutation", "credentialed_action"],
                "credential_scope": "service_bearer" if credentialed_patch else "none",
                "external_actions": {
                    "write": [
                        {
                            "id": "write-1",
                            "method": "POST",
                            "path": "/actions/write",
                            "content_type": "application/json",
                            "body": "{\"synthetic\":true}",
                        }
                    ],
                    "mutation": [
                        {
                            "id": "put-1",
                            "method": "PUT",
                            "path": "/actions/item",
                            "content_type": "application/json",
                            "body": "{\"synthetic\":true}",
                        },
                        {
                            "id": "patch-1",
                            "method": "PATCH",
                            "path": "/actions/item",
                            "content_type": "application/json",
                            "body": "{\"synthetic\":true,\"v\":2}",
                            "requires_credential": credentialed_patch,
                        },
                        {
                            "id": "delete-is-not-an-execution-contract-method",
                            "method": "DELETE",
                            "path": "/actions/item",
                            "body": None,
                        },
                    ],
                },
            }
        },
    }


def _install_fake_client(monkeypatch, calls: list[dict]) -> None:
    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "body": body,
                    "headers": dict(headers or {}),
                }
            )
            return SimpleNamespace(
                body=b"ok",
                receipt=SimpleNamespace(
                    status=200,
                    final_url=url,
                    response_sha256="00" * 32,
                ),
            )

    monkeypatch.setattr(module, "ExternalContactClient", FakeClient)


def test_live_lease_is_execution_contract_without_canonical_registry(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(state / "discovery_policy.json", _policy())
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease(now)]},
    )

    calls: list[dict] = []
    _install_fake_client(monkeypatch, calls)
    result = module.run_discovery_external_actions(state, repo_root=repo, max_actions=8)

    assert result["attempted"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert result["denied_before_execution"] == 0
    assert result["canonical_registry_recheck"] is False
    assert [call["method"] for call in calls] == ["POST", "PUT", "PATCH"]
    assert all(call["url"].startswith("https://owner.example/") for call in calls)
    assert all(row["contract"]["lease_id"] == "lease-1" for row in result["receipts"])


def test_credentialed_mutation_binds_only_to_same_live_contract(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(state / "discovery_policy.json", _policy(credentialed_patch=True))
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease(now, credentialed=True)]},
    )

    calls: list[dict] = []
    _install_fake_client(monkeypatch, calls)
    resolved: list[tuple[str, str]] = []

    def resolver(lease, action):
        resolved.append((lease.target, action["id"]))
        return {"Authorization": "Bearer runtime-only-secret"}

    result = module.run_discovery_external_actions(
        state,
        repo_root=repo,
        max_actions=8,
        credential_headers_resolver=resolver,
    )

    assert result["attempted"] == 3
    assert result["succeeded"] == 3
    assert resolved == [("owner.example", "patch-1")]
    patch_call = next(call for call in calls if call["method"] == "PATCH")
    assert patch_call["headers"]["Authorization"] == "Bearer runtime-only-secret"
    patch_receipt = next(row for row in result["receipts"] if row.get("action_id") == "patch-1")
    assert patch_receipt["credential_bound"] is True
    assert patch_receipt["credential_scope"] == "service_bearer"


def test_credentialed_mutation_does_not_search_for_alternate_credential(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(state / "discovery_policy.json", _policy(credentialed_patch=True))
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease(now, credentialed=True)]},
    )

    calls: list[dict] = []
    _install_fake_client(monkeypatch, calls)
    result = module.run_discovery_external_actions(state, repo_root=repo, max_actions=8)

    assert result["attempted"] == 2
    assert result["succeeded"] == 2
    assert result["denied_before_execution"] == 1
    assert result["alternate_host_path_or_credential_exploration"] is False
    assert [call["method"] for call in calls] == ["POST", "PUT"]
    denial = next(row for row in result["receipts"] if row.get("action_id") == "patch-1")
    assert denial["reason"] == "credential_binding_adapter_unavailable"
