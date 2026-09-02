from __future__ import annotations

import json
import urllib.error

import pytest

from senju.credential_runtime import CredentialRecoveryRuntime, CredentialRuntimeError
from senju.credential_self_tuner import TuneOutcome, TuneStrategy
from senju.meta import agent_dispatch


def _env(**extra: str) -> dict[str, str]:
    base = {
        "GITHUB_TOKEN": "current-token-value",
        "GITHUB_REPOSITORY": "MusicJapanLLC/test",
    }
    base.update(extra)
    return base


def test_runtime_uses_already_provisioned_github_token_without_persisting_secret(tmp_path) -> None:
    runtime = CredentialRecoveryRuntime.from_environment(
        actor="META",
        environ=_env(),
        state_dir=tmp_path,
    )
    result = runtime.recover(
        provider="github",
        required_scopes={"issues:write"},
        operation="github_issue_create",
        resource="/repos/MusicJapanLLC/test/issues",
        error_code="http_403",
    )
    assert result.outcome is TuneOutcome.RECOVERED
    assert result.strategy is TuneStrategy.PREAPPROVED_GRANT_SWITCH
    assert result.authority_changed is False

    history = (tmp_path / "credential_tuning_history.json").read_text(encoding="utf-8")
    memory = (tmp_path / "credential_secret_memory.json").read_text(encoding="utf-8")
    assert "current-token-value" not in history
    assert "current-token-value" not in memory
    assert "env://GITHUB_TOKEN" not in history
    assert "env://GITHUB_TOKEN" not in memory


def test_runtime_prefers_smallest_explicitly_provisioned_grant(monkeypatch, tmp_path) -> None:
    config = [
        {
            "grant_id": "github-issues-only",
            "provider": "github",
            "env_var": "META_ISSUES_TOKEN",
            "allowed_scopes": ["issues:write"],
            "required_authority_scope": "service_bearer",
            "max_ttl_seconds": 300,
        }
    ]
    monkeypatch.setenv("GITHUB_TOKEN", "current-token-value")
    monkeypatch.setenv("META_ISSUES_TOKEN", "issues-only-token")
    monkeypatch.setenv("SENJU_CREDENTIAL_GRANTS_JSON", json.dumps(config))

    runtime = CredentialRecoveryRuntime.from_environment(actor="META", state_dir=tmp_path)
    result = runtime.recover(
        provider="github",
        required_scopes={"issues:write"},
        operation="github_issue_create",
    )
    assert result.recovered
    assert result.grant_id == "github-issues-only"
    assert runtime.resolve_selected_secret(result) == "issues-only-token"


def test_runtime_never_auto_creates_unapproved_scope(tmp_path) -> None:
    runtime = CredentialRecoveryRuntime.from_environment(
        actor="X",
        environ=_env(),
        state_dir=tmp_path,
    )
    result = runtime.recover(
        provider="github",
        required_scopes={"packages:write"},
        operation="publish_package",
    )
    assert result.outcome is TuneOutcome.APPROVAL_REQUIRED
    assert result.lease_id is None
    assert result.authority_changed is False


def test_runtime_denies_privileged_scope(tmp_path) -> None:
    runtime = CredentialRecoveryRuntime.from_environment(
        actor="META",
        environ=_env(),
        state_dir=tmp_path,
    )
    result = runtime.recover(
        provider="github",
        required_scopes={"repo:admin"},
        operation="change_repo_admin",
    )
    assert result.outcome is TuneOutcome.DENIED
    assert result.strategy is TuneStrategy.DENY_PRIVILEGED_SCOPE


def test_runtime_config_rejects_embedded_raw_secret() -> None:
    bad = json.dumps(
        [
            {
                "grant_id": "bad",
                "provider": "github",
                "env_var": "ALT_TOKEN",
                "allowed_scopes": ["issues:write"],
                "token": "raw-secret-must-not-live-here",
            }
        ]
    )
    with pytest.raises(Exception):
        CredentialRecoveryRuntime.from_environment(
            actor="META",
            environ={
                "ALT_TOKEN": "actual-runtime-secret",
                "SENJU_CREDENTIAL_GRANTS_JSON": bad,
            },
        )


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _issues_config() -> list[dict[str, object]]:
    return [
        {
            "grant_id": "github-issues-only",
            "provider": "github",
            "env_var": "META_ISSUES_TOKEN",
            "allowed_scopes": ["issues:write"],
            "required_authority_scope": "service_bearer",
            "max_ttl_seconds": 300,
        }
    ]


def test_agent_dispatch_403_invokes_tuner_and_retries_with_selected_preapproved_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "current-token-value")
    monkeypatch.setenv("META_ISSUES_TOKEN", "issues-only-token")
    monkeypatch.setenv("SENJU_CREDENTIAL_GRANTS_JSON", json.dumps(_issues_config()))

    runtime = CredentialRecoveryRuntime.from_environment(actor="META", state_dir=tmp_path)
    monkeypatch.setattr(agent_dispatch, "_credential_runtime", lambda actor: runtime)
    monkeypatch.setattr(agent_dispatch, "GITHUB_TOKEN", "current-token-value")

    seen: list[str] = []

    def fake_urlopen(req, timeout=15):
        auth = req.get_header("Authorization") or ""
        seen.append(auth)
        if auth == "token current-token-value":
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=None)
        if auth == "token issues-only-token":
            return _Response(b'{"ok":"recovered"}')
        raise AssertionError(f"unexpected authorization header: {auth}")

    monkeypatch.setattr(agent_dispatch.urllib.request, "urlopen", fake_urlopen)

    result = agent_dispatch._gh_api(
        "POST",
        "/repos/MusicJapanLLC/test/issues",
        {"title": "test"},
        required_scopes=frozenset({"issues:write"}),
        operation="github_issue_create",
        actor="META",
    )

    assert result["ok"] == "recovered"
    assert result["_retried_after_permission_failure"] is True
    assert result["_credential_recovery"]["grant_id"] == "github-issues-only"
    assert result["_credential_recovery"]["authority_changed"] is False
    assert seen == ["token current-token-value", "token issues-only-token"]


def test_recovery_learning_is_loaded_by_next_runtime(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "current-token-value")
    monkeypatch.setenv("META_ISSUES_TOKEN", "issues-only-token")
    monkeypatch.setenv("SENJU_CREDENTIAL_GRANTS_JSON", json.dumps(_issues_config()))

    first = CredentialRecoveryRuntime.from_environment(actor="META", state_dir=tmp_path)

    result, response = first.recover_operation(
        provider="github",
        required_scopes={"issues:write"},
        operation="github_issue_create",
        resource="/repos/MusicJapanLLC/test/issues",
        error_code="http_403",
        attempt_with_secret=lambda secret: {"ok": True} if secret == "issues-only-token" else {"_error": 403},
    )
    assert result.recovered
    assert result.grant_id == "github-issues-only"
    assert response == {"ok": True}
    assert first.recovery_loop.grant_successes["github-issues-only"] == 1

    second = CredentialRecoveryRuntime.from_environment(actor="META", state_dir=tmp_path)
    assert second.recovery_loop.grant_successes["github-issues-only"] == 1
    learned = (tmp_path / "credential_recovery_learning.json").read_text(encoding="utf-8")
    assert "issues-only-token" not in learned
    assert "current-token-value" not in learned
