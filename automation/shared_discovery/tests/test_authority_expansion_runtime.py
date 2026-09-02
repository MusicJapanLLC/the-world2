from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from engine import authority_expansion_runtime as expansion


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(repo: Path, *, host: str = "owner.example", explicit: bool = True, methods=None) -> None:
    methods = methods or ["GET", "HEAD", "POST", "PUT", "PATCH"]
    targets = []
    if explicit:
        targets.append(
            {
                "host": host,
                "base_url": f"https://{host}",
                "owner_authorization": "explicit",
                "allowed_interactions": methods,
            }
        )
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"targets": targets})


def _policy(host: str = "owner.example", *, fastpath: bool = True) -> dict:
    return {
        "action_profiles": {
            host: {
                "owner_authorization": "explicit",
                "capabilities": ["credentialed_action"],
                "credential_scope": "service_bearer",
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
                            "credential_grant_ids": ["primary", "secondary"],
                            "required_scopes": ["synthetic:write"],
                            "credential_ttl_seconds": 120,
                            "payload_mode": "ai_candidate_or_meta_synthesis",
                        }
                    ]
                },
                "authority_expansion": {
                    "enabled": True,
                    "auto_approve_inside_existing_owner_envelope": fastpath,
                    "credential_scope_policy": "same_only",
                    "routes": {
                        "credentialed-patch": [
                            {
                                "route_id": "post-record-endpoint",
                                "method": "POST",
                                "path": "/records/current",
                                "priority": 0,
                            },
                            {
                                "route_id": "put-alt-record-endpoint",
                                "method": "PUT",
                                "path": "/records/current-alt-2",
                                "priority": 1,
                            },
                        ]
                    },
                },
            }
        }
    }


def _failed_receipt(host: str = "owner.example", classification: str = "http_failure") -> dict:
    return {
        "schema": "meta-discovery-external-actions/v3",
        "receipts": [
            {
                "target": host,
                "capability": "credentialed_action",
                "action_id": "credentialed-patch",
                "method": "PATCH",
                "status": "failed",
                "classification": classification,
                "credential_scope": "service_bearer",
            }
        ],
    }


def _lease(now: int, host: str = "owner.example") -> dict:
    return {
        "lease_id": "lease-1",
        "target": host,
        "url": f"https://{host}/",
        "authorization_reference": "canonical:explicit-owner-test-host",
        "authorization_basis": "explicit_owner_authorized_target",
        "capability_authorization_profile": host,
        "capability_inherited_from_owner_root": False,
        "capabilities": ["credentialed_action"],
        "credential_scope": "service_bearer",
        "shared_with": ["META", "X", "SENJU"],
        "issued_at": now - 10,
        "expires_at": now + 3600,
        "source_action_fingerprint": "abc123",
        "status": "active",
    }


def test_failure_automatically_becomes_expansion_case_and_owner_fastpath(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy())
    _write(state / "discovery_external_action_receipts.json", _failed_receipt())

    result = expansion.build_authority_expansion_cases(state, repo_root=repo)

    assert result["case_count"] == 1
    case = result["cases"][0]
    assert case["current_stage"] == "approved_route_ready"
    assert case["approval_basis"] == "existing_explicit_owner_envelope"
    assert case["approval_coordinator"] == "META"
    assert case["cross_host_expansion_allowed"] is False
    assert case["credential_scope_expansion_allowed"] is False
    queue = json.loads((state / "authority_expansion_route_queue.json").read_text())
    assert [row["method"] for row in queue["routes"][0]["routes"]] == ["POST", "PUT"]


def test_unknown_host_creates_case_but_never_approved_route(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo, explicit=False)
    _write(state / "discovery_policy.json", _policy())
    _write(state / "discovery_external_action_receipts.json", _failed_receipt())

    result = expansion.build_authority_expansion_cases(state, repo_root=repo)

    case = result["cases"][0]
    assert case["current_stage"] == "external_authorization_required"
    assert case["approved_routes"] == []
    assert case["next_action"] == "META_collect_explicit_authorization"
    queue = json.loads((state / "authority_expansion_route_queue.json").read_text())
    assert queue["route_case_count"] == 0


def test_method_outside_owner_scope_is_not_fastpath_approved(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo, methods=["GET", "HEAD", "PATCH"])
    _write(state / "discovery_policy.json", _policy())
    _write(state / "discovery_external_action_receipts.json", _failed_receipt())

    result = expansion.build_authority_expansion_cases(state, repo_root=repo)

    case = result["cases"][0]
    assert case["approved_routes"] == []
    assert case["blocking_reason"] == "requested_method_not_in_owner_scope"


def test_three_of_three_decision_can_activate_route_when_fastpath_disabled(tmp_path: Path) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy(fastpath=False))
    _write(state / "discovery_external_action_receipts.json", _failed_receipt())

    first = expansion.build_authority_expansion_cases(state, repo_root=repo)
    case_id = first["cases"][0]["case_id"]
    assert first["cases"][0]["current_stage"] == "awaiting_approval"
    _write(
        state / "authority_expansion_decisions.json",
        {
            "decisions": [
                {
                    "case_id": case_id,
                    "approved": True,
                    "approved_by": ["META", "X", "SENJU"],
                }
            ]
        },
    )

    second = expansion.build_authority_expansion_cases(state, repo_root=repo)
    assert second["cases"][0]["current_stage"] == "approved_route_ready"
    assert second["cases"][0]["approval_basis"] == "META_X_SENJU_3_of_3"


def test_approved_route_switch_executes_on_same_exact_host_with_credential(tmp_path: Path, monkeypatch) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _repo(repo)
    _write(state / "discovery_policy.json", _policy())
    _write(state / "discovery_external_action_receipts.json", _failed_receipt())
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [_lease(now)]},
    )
    expansion.build_authority_expansion_cases(state, repo_root=repo)

    calls: list[dict] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            calls.append({"url": url, "method": method, "headers": dict(headers or {})})
            return SimpleNamespace(
                body=b"ok",
                receipt=SimpleNamespace(
                    status=200,
                    final_url=url,
                    response_sha256="11" * 32,
                ),
            )

    class Resolver:
        def __call__(self, lease, action):
            return {"Authorization": "Bearer synthetic-test"}

        def report_http_status(self, action_id, status):
            return None

        def flush(self):
            return None

    monkeypatch.setattr(expansion, "ExternalContactClient", FakeClient)
    result = expansion.execute_approved_authority_expansion_routes(
        state,
        repo_root=repo,
        credential_headers_resolver=Resolver(),
        payload_resolver=lambda lease, action: SimpleNamespace(
            body=b'{"synthetic":true,"expanded":true}', source="META"
        ),
    )

    assert result["succeeded"] == 1
    assert result["same_exact_owner_host_only"] is True
    assert len(calls) == 1
    assert calls[0]["url"] == "https://owner.example/records/current"
    assert calls[0]["method"] == "POST"
    assert calls[0]["headers"]["Authorization"] == "Bearer synthetic-test"
