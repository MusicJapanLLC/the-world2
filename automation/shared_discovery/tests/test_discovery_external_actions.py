from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from engine.discovery_external_actions import (
    execute_discovery_external_actions,
    plan_discovery_external_actions,
)


NOW = 1_788_174_600


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lease(
    *,
    target: str = "owner.example",
    capabilities: list[str] | None = None,
    profile: str = "owner.example",
    inherited: bool = False,
    expires_at: int = NOW + 3600,
    credential_scope: str = "none",
) -> dict[str, object]:
    caps = capabilities or ["scan", "probe", "write", "mutation"]
    return {
        "lease_id": f"discovery:{target}:abc:{NOW}",
        "target": target,
        "url": f"https://{target}/",
        "authorization_reference": f"owner:test:{target}",
        "authorization_basis": "trusted_root",
        "capability_authorization_profile": profile,
        "capability_inherited_from_owner_root": inherited,
        "capabilities": caps,
        "credential_scope": credential_scope,
        "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
        "issued_at": NOW,
        "expires_at": expires_at,
        "source_action_fingerprint": "abc",
        "status": "active",
    }


def _policy(*, inherit: bool = False) -> dict[str, object]:
    return {
        "schema": "meta-discovery-policy/v3",
        "action_profiles": {
            "owner.example": {
                "owner_authorization": "explicit",
                "inherit_to_descendants": inherit,
                "capabilities": ["scan", "probe", "write", "mutation"],
                "credential_scope": "none",
                "external_actions": {
                    "write": [
                        {
                            "id": "contact-write",
                            "method": "POST",
                            "path": "/contact",
                            "content_type": "application/x-www-form-urlencoded",
                            "body": "name=world&message=authorized",
                        }
                    ],
                    "mutation": [
                        {
                            "id": "record-create",
                            "method": "PUT",
                            "path": "/synthetic/world",
                            "content_type": "application/json",
                            "body": '{"synthetic":true}',
                        },
                        {
                            "id": "record-update",
                            "method": "PATCH",
                            "path": "/synthetic/world",
                            "content_type": "application/json",
                            "body": '{"value":2}',
                        },
                        {
                            "id": "record-delete",
                            "method": "DELETE",
                            "path": "/synthetic/world",
                            "content_type": "application/json",
                            "body": None,
                        },
                    ],
                },
            }
        },
    }


def _state(tmp_path: Path, *, lease: dict[str, object] | None = None, policy: dict[str, object] | None = None) -> Path:
    state = tmp_path / "meta_state"
    state.mkdir(parents=True)
    _write(state / "discovery_policy.json", policy or _policy())
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "generated_at": NOW,
            "leases": [lease or _lease()],
        },
    )
    return state


class _FakeClient:
    def __init__(self, policy, calls: list[dict[str, object]], *, final_host: str | None = None) -> None:
        self.policy = policy
        self.calls = calls
        self.final_host = final_host

    def contact_with_body(self, url, *, method="GET", body=None, headers=None):
        self.calls.append(
            {
                "url": url,
                "method": method,
                "body": body,
                "headers": headers,
                "allow_hosts": set(self.policy.allow_hosts),
                "allow_delete": self.policy.allow_delete,
                "allowed_methods": set(self.policy.allowed_methods),
            }
        )
        if self.final_host:
            final_url = f"https://{self.final_host}/escaped"
        else:
            final_url = url
        receipt = SimpleNamespace(status=204, final_url=final_url)
        return SimpleNamespace(receipt=receipt, body=b"ok")


def test_exact_owner_profile_executes_predeclared_write_and_mutation_actions(tmp_path: Path) -> None:
    state = _state(tmp_path)
    planned = plan_discovery_external_actions(state, now=NOW)
    assert len(planned) == 4
    assert {row.method for row in planned} == {"POST", "PUT", "PATCH", "DELETE"}
    assert all(row.target == "owner.example" for row in planned)

    calls: list[dict[str, object]] = []
    result = execute_discovery_external_actions(
        state,
        now=NOW,
        client_factory=lambda policy: _FakeClient(policy, calls),
    )
    assert result["planned_count"] == 4
    assert result["attempted"] == 4
    assert result["succeeded"] == 4
    assert result["failed"] == 0
    assert result["denied"] == 0
    assert {row["method"] for row in calls} == {"POST", "PUT", "PATCH", "DELETE"}
    assert all(row["allow_hosts"] == {"owner.example"} for row in calls)
    assert all(row["allowed_methods"] == {row["method"]} for row in calls)
    assert next(row for row in calls if row["method"] == "DELETE")["allow_delete"] is True
    assert all(row["allow_delete"] is False for row in calls if row["method"] != "DELETE")

    receipts = json.loads((state / "discovery_external_action_receipts.json").read_text())
    assert receipts["schema"] == "meta-discovery-external-action-receipts/v1"
    assert receipts["succeeded"] == 4
    assert receipts["authority_expansion_on_failure"] is False
    assert receipts["alternate_target_on_failure"] is False
    assert all("body" not in row for row in receipts["receipts"])


def test_unrelated_or_uninherited_target_cannot_consume_root_external_actions(tmp_path: Path) -> None:
    state = _state(
        tmp_path,
        lease=_lease(target="api.owner.example", profile="owner.example", inherited=False),
        policy=_policy(inherit=True),
    )
    assert plan_discovery_external_actions(state, now=NOW) == ()


def test_explicit_inheritance_flag_can_apply_predeclared_actions_to_authorized_descendant(tmp_path: Path) -> None:
    state = _state(
        tmp_path,
        lease=_lease(target="api.owner.example", profile="owner.example", inherited=True),
        policy=_policy(inherit=True),
    )
    planned = plan_discovery_external_actions(state, now=NOW)
    assert len(planned) == 4
    assert all(row.target == "api.owner.example" for row in planned)
    assert all(row.capability_inherited_from_owner_root is True for row in planned)


def test_expired_lease_cannot_plan_or_execute_external_actions(tmp_path: Path) -> None:
    state = _state(tmp_path, lease=_lease(expires_at=NOW - 1))
    assert plan_discovery_external_actions(state, now=NOW) == ()
    calls: list[dict[str, object]] = []
    result = execute_discovery_external_actions(
        state,
        now=NOW,
        client_factory=lambda policy: _FakeClient(policy, calls),
    )
    assert result["attempted"] == 0
    assert calls == []


def test_credentialed_action_is_not_materialized_by_generic_executor(tmp_path: Path) -> None:
    policy = _policy()
    policy["action_profiles"]["owner.example"]["capabilities"].append("credentialed_action")
    policy["action_profiles"]["owner.example"]["external_actions"]["credentialed_action"] = [
        {"id": "secret-call", "method": "POST", "path": "/secret", "body": "x=1"}
    ]
    state = _state(
        tmp_path,
        lease=_lease(
            capabilities=["scan", "probe", "write", "mutation", "credentialed_action"],
            credential_scope="preapproved-service",
        ),
        policy=policy,
    )
    planned = plan_discovery_external_actions(state, now=NOW)
    assert all(row.capability != "credentialed_action" for row in planned)


def test_final_url_escape_is_failed_without_changing_authority_or_target(tmp_path: Path) -> None:
    state = _state(tmp_path)
    calls: list[dict[str, object]] = []
    result = execute_discovery_external_actions(
        state,
        now=NOW,
        max_actions=1,
        client_factory=lambda policy: _FakeClient(policy, calls, final_host="outside.example"),
    )
    assert result["attempted"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert result["authority_expansion_on_failure"] is False
    assert result["alternate_target_on_failure"] is False
    assert calls[0]["allow_hosts"] == {"owner.example"}
