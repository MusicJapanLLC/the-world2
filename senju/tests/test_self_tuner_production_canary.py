from senju.meta import self_tuner
from senju.meta.policy_workspace import PRODUCTION_CANARY_KEY


def test_self_tuner_can_apply_restrictive_production_canary(monkeypatch, tmp_path):
    monkeypatch.setattr(self_tuner, "STATE_DIR", tmp_path)
    monkeypatch.setattr(self_tuner, "TUNER_CONFIG", tmp_path / "meta_tuner_config.json")
    monkeypatch.setattr(self_tuner, "TUNER_LOG", tmp_path / "meta_tuner_log.ndjson")

    workspace = {
        "credential_scope": {
            "scopes": ["read:repo", "read:issues"],
            "max_tokens": 2,
        }
    }
    outcome = self_tuner.edit_governance_policy(
        "credential scope",
        {"scopes": ["read:repo"], "max_tokens": 1},
        environment="production",
        workspace=workspace,
        canary_scope="meta-canary-1",
    )

    result = outcome["result"]
    assert result["applied"] is True
    assert result["canary_applied"] is True
    assert workspace["credential_scope"] == {
        "scopes": ["read:repo", "read:issues"],
        "max_tokens": 2,
    }
    assert workspace[PRODUCTION_CANARY_KEY]["meta-canary-1"]["credential_scope"] == {
        "scopes": ["read:repo"],
        "max_tokens": 1,
    }

    assert self_tuner.resolve_governance_policy(
        workspace,
        "credential scope",
        environment="production",
        canary_scope="meta-canary-1",
    ) == {"scopes": ["read:repo"], "max_tokens": 1}
    assert self_tuner.resolve_governance_policy(
        workspace,
        "credential scope",
        environment="production",
        canary_scope="normal-runtime",
    ) == {"scopes": ["read:repo", "read:issues"], "max_tokens": 2}


def test_self_tuner_production_canary_rejects_expansion(monkeypatch, tmp_path):
    monkeypatch.setattr(self_tuner, "STATE_DIR", tmp_path)
    monkeypatch.setattr(self_tuner, "TUNER_CONFIG", tmp_path / "meta_tuner_config.json")
    monkeypatch.setattr(self_tuner, "TUNER_LOG", tmp_path / "meta_tuner_log.ndjson")

    workspace = {"credential_scope": {"scopes": ["read:repo"]}}

    try:
        self_tuner.edit_governance_policy(
            "credential scope",
            {"scopes": ["read:repo", "write:repo"]},
            environment="production",
            workspace=workspace,
            canary_scope="meta-canary-1",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("production canary expanded credential scope")
