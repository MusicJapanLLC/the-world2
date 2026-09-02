from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from engine.credential_bound_mutation import execute_credential_bound_mutations
from senju.external import ExternalContactError

HOST = "kabeya-authorized-test-range.onrender.com"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(tmp_path: Path, *, host: str = HOST, method: str = "PATCH", scope: str = "synthetic_test_bearer", variants: int = 1) -> Path:
    repo = tmp_path / "repo"
    _write(
        repo / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "host": HOST,
                    "owner_authorization": "explicit",
                }
            ]
        },
    )
    _write(
        repo / "automation" / "codegen" / "config" / "credential_bound_mutation.json",
        {
            "schema": "the-world-credential-bound-mutation-config/v1",
            "bindings": [
                {
                    "id": "test-binding",
                    "host": host,
                    "owner_authorization": "explicit",
                    "credential_scope": scope,
                    "secret_env": "TEST_TOKEN",
                    "header": "Authorization",
                    "prefix": "Bearer ",
                    "methods": ["POST", "PUT", "PATCH"],
                    "synthetic_only": True,
                }
            ],
            "mutations": [
                {
                    "id": "test-mutation",
                    "host": host,
                    "credential_binding": "test-binding",
                    "capability": "mutation",
                    "method": method,
                    "primary_path": "/login-lab/synthetic-records/credential-loop",
                    "alternate_paths": ["/login-lab/synthetic-records/credential-loop-alt"],
                    "content_type": "application/json",
                    "payload_mode": "json_synthetic",
                    "static_fields": {"operation": "update"},
                    "payload_variants": variants,
                }
            ],
            "limits": {
                "max_mutations_per_cycle": 4,
                "max_attempts_per_mutation": 4,
                "max_request_bytes": 16384,
                "max_response_bytes": 131072,
            },
        },
    )
    return repo


def _lease(state: Path, *, host: str = HOST, scope: str = "synthetic_test_bearer") -> None:
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [
                {
                    "lease_id": "lease-1",
                    "target": host,
                    "url": f"https://{host}/",
                    "authorization_reference": "owner-explicit-test-range",
                    "authorization_basis": "explicit_owner_target",
                    "capability_authorization_profile": host,
                    "capability_inherited_from_owner_root": False,
                    "capabilities": ["write", "mutation", "credentialed_action"],
                    "credential_scope": scope,
                    "shared_with": ["META", "X", "SENJU"],
                    "issued_at": 1000,
                    "expires_at": 9000,
                    "source_action_fingerprint": "abc123",
                    "status": "active",
                }
            ],
        },
    )


class FakeClient:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls: list[dict] = []

    def contact_with_body(self, url: str, *, method: str, body: bytes | None, headers: dict | None):
        self.calls.append({"url": url, "method": method, "body": body, "headers": dict(headers or {})})
        if self.fail_first and len(self.calls) == 1:
            raise ExternalContactError("synthetic first-path failure")
        return SimpleNamespace(
            receipt=SimpleNamespace(final_url=url, status=200),
            body=b'{"ok":true}',
        )


def test_credential_bound_patch_executes_and_secret_is_not_persisted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state = tmp_path / "state"
    _lease(state)
    client = FakeClient()

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={"TEST_TOKEN": "super-secret-test-value"},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 1
    assert result["secret_persisted"] is False
    assert len(client.calls) == 1
    assert client.calls[0]["method"] == "PATCH"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer super-secret-test-value"
    assert b'"synthetic":true' in client.calls[0]["body"]
    receipt_text = (state / "credential_bound_mutation_receipts.json").read_text()
    assert "super-secret-test-value" not in receipt_text
    assert "test-binding" in receipt_text


def test_failure_retries_on_same_host_alternate_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path, variants=1)
    state = tmp_path / "state"
    _lease(state)
    client = FakeClient(fail_first=True)

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={"TEST_TOKEN": "token"},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 1
    assert len(client.calls) == 2
    assert client.calls[0]["url"] == f"https://{HOST}/login-lab/synthetic-records/credential-loop"
    assert client.calls[1]["url"] == f"https://{HOST}/login-lab/synthetic-records/credential-loop-alt"
    receipts = json.loads((state / "credential_bound_mutation_receipts.json").read_text())["receipts"]
    assert receipts[0]["status"] == "failed"
    assert receipts[1]["status"] == "success"
    assert receipts[1]["alternate_path"] is True
    assert all(row["host"] == HOST for row in receipts)


def test_missing_configured_test_credential_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state = tmp_path / "state"
    _lease(state)
    client = FakeClient()

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 0
    assert result["denied_mutations"] == 1
    assert client.calls == []


def test_unknown_host_cannot_use_credential_even_with_lease_and_secret(tmp_path: Path) -> None:
    unknown = "unrelated-third-party.example"
    repo = _repo(tmp_path, host=unknown)
    state = tmp_path / "state"
    _lease(state, host=unknown)
    client = FakeClient()

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={"TEST_TOKEN": "token"},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 0
    assert result["denied_mutations"] == 1
    assert client.calls == []


def test_credential_scope_must_match_current_authority_lease(tmp_path: Path) -> None:
    repo = _repo(tmp_path, scope="synthetic_test_bearer")
    state = tmp_path / "state"
    _lease(state, scope="different-scope")
    client = FakeClient()

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={"TEST_TOKEN": "token"},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 0
    assert result["denied_mutations"] == 1
    assert client.calls == []


def test_delete_is_never_part_of_credential_bound_mutation_lane(tmp_path: Path) -> None:
    repo = _repo(tmp_path, method="DELETE")
    state = tmp_path / "state"
    _lease(state)
    client = FakeClient()

    result = execute_credential_bound_mutations(
        state,
        repo_root=repo,
        environ={"TEST_TOKEN": "token"},
        now=2000,
        client_factory=lambda _policy: client,
    )

    assert result["successful_mutations"] == 0
    assert result["denied_mutations"] == 1
    assert client.calls == []
