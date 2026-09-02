from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.authorized_credential_mutation import (
    AuthorizedCredentialMutationError,
    run_authorized_credential_mutation,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _repo(tmp_path: Path, *, allow_methods: tuple[str, ...] = ("POST", "PUT", "PATCH")) -> Path:
    root = tmp_path / "repo"
    _write(
        root / "AUTHORIZED_TEST_TARGETS.json",
        {
            "targets": [
                {
                    "owner_authorization": "explicit",
                    "host": "owned.example.com",
                    "allowed_interactions": ["GET", "HEAD", *allow_methods],
                }
            ]
        },
    )
    return root


def _plan(tmp_path: Path, *, target: str = "owned.example.com", method: str = "POST") -> Path:
    path = tmp_path / "plan.json"
    _write(
        path,
        {
            "schema": "the-world-authorized-credential-mutation-plan/v1",
            "mode": "synthetic_test_only",
            "target": target,
            "synthetic_credentials": [
                {
                    "credential_id": "synthetic-1",
                    "target": target,
                    "env_var": "AUTHORIZED_TEST_SYNTHETIC_TOKEN",
                    "header": "Authorization",
                    "prefix": "Bearer ",
                    "synthetic_only": True,
                }
            ],
            "actions": [
                {
                    "id": "a1",
                    "method": method,
                    "path": "/primary",
                    "alternate_paths": ["/fallback"],
                    "content_type": "application/json",
                    "body": "{\"synthetic\":true}",
                }
            ],
        },
    )
    return path


def test_rejects_unknown_target(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(tmp_path, target="third-party.example.net")
    with pytest.raises(AuthorizedCredentialMutationError, match="exact explicit owner-authorized"):
        run_authorized_credential_mutation(plan, repo_root=root, state_dir=tmp_path / "state")


def test_rejects_method_not_explicitly_authorized(tmp_path: Path) -> None:
    root = _repo(tmp_path, allow_methods=())
    plan = _plan(tmp_path, method="POST")
    with pytest.raises(AuthorizedCredentialMutationError, match="not explicitly authorized"):
        run_authorized_credential_mutation(plan, repo_root=root, state_dir=tmp_path / "state")


def test_dry_run_reports_bundle_without_side_effects(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(tmp_path)
    result = run_authorized_credential_mutation(
        plan,
        repo_root=root,
        state_dir=tmp_path / "state",
        execute=False,
        environ={"AUTHORIZED_TEST_SYNTHETIC_TOKEN": "secret-value"},
        now=100,
    )
    assert result["authority_lease_required"] is True
    assert result["credential_binding_required"] is True
    assert result["credential_discovery_mode"] == "declared_synthetic_metadata_only"
    assert result["payload_generation"] == "bounded_structured_synthetic_variants"
    assert result["alternate_path_mode"] == "predeclared_same_origin_only"
    assert result["external_side_effects"] is False


def test_execute_revalidates_authority_and_uses_predeclared_fallback(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(tmp_path)
    state = tmp_path / "state"
    calls: list[dict] = []
    lease_calls: list[tuple[str, str]] = []

    def authority_resolver(_state, *, target, capability, now):
        lease_calls.append((target, capability))
        return SimpleNamespace(lease_id=f"lease-{len(lease_calls)}")

    responses = [500, 200]

    class Client:
        def contact_with_body(self, url, *, method, body, headers):
            calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
            status = responses.pop(0)
            return SimpleNamespace(
                receipt=SimpleNamespace(status=status, final_url=url),
                body=f"status={status}".encode(),
            )

    result = run_authorized_credential_mutation(
        plan,
        repo_root=root,
        state_dir=state,
        execute=True,
        environ={"AUTHORIZED_TEST_SYNTHETIC_TOKEN": "super-secret"},
        client_factory=lambda _policy: Client(),
        authority_resolver=authority_resolver,
        now=100,
    )

    assert result["succeeded"] == 1
    assert len(calls) == 2
    assert calls[0]["url"].endswith("/primary")
    assert calls[1]["url"].endswith("/fallback")
    assert calls[0]["headers"]["Authorization"] == "Bearer super-secret"
    assert lease_calls == [
        ("owned.example.com", "write"),
        ("owned.example.com", "write"),
    ]

    receipt_text = (state / "authorized_credential_mutation_receipts.json").read_text()
    assert "super-secret" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["credential_secret_recorded"] is False
    assert receipt["authority_revalidated_before_every_attempt"] is True
    assert receipt["host_changed_after_failure"] is False
    assert receipt["method_widened_after_failure"] is False


def test_does_not_scan_undeclared_environment_credentials(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = _plan(tmp_path)
    result = run_authorized_credential_mutation(
        plan,
        repo_root=root,
        state_dir=tmp_path / "state",
        execute=False,
        environ={"RANDOM_REAL_TOKEN": "must-not-be-used"},
        now=100,
    )
    assert result["credential_id"] == "synthetic-1"
    assert result["credential_available"] is False
