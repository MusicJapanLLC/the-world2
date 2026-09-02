from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from automation.recovery.approved_persistence import build_recovery_plan


def _registry(tmp_path: Path, worker: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "policy": {
            "unknown_system_installation": "deny",
            "require_owner_authorized": True,
            "same_repository_only": True,
            "allowed_providers": ["github_actions"],
            "max_recovery_dispatches_per_run": 3,
        },
        "workers": [worker],
    }), encoding="utf-8")
    return path


def test_missing_heartbeat_produces_same_repo_dispatch(tmp_path: Path) -> None:
    registry = _registry(tmp_path, {
        "id": "meta",
        "owner_authorized": True,
        "provider": "github_actions",
        "heartbeat_file": "senju/state/does-not-exist.json",
        "heartbeat_field": "alive_at",
        "stale_after_seconds": 600,
        "recovery": {"kind": "workflow_dispatch", "workflow": "meta-consciousness.yml", "ref": "main"},
    })
    plan = build_recovery_plan(registry, now=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc))
    assert plan["unknown_system_installation"] is False
    assert plan["self_installation"] is False
    assert plan["same_repository_only"] is True
    assert plan["actions"][0]["workflow"] == "meta-consciousness.yml"


def test_unowned_worker_is_never_eligible(tmp_path: Path) -> None:
    registry = _registry(tmp_path, {
        "id": "unknown-host",
        "owner_authorized": False,
        "provider": "github_actions",
        "heartbeat_file": "senju/state/missing.json",
        "recovery": {"kind": "workflow_dispatch", "workflow": "x.yml", "ref": "main"},
    })
    plan = build_recovery_plan(registry)
    assert plan["actions"] == []
    assert plan["observations"][0]["reason"] == "owner_authorization_missing"


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path, {
        "id": "external",
        "owner_authorized": True,
        "provider": "unknown_external_system",
        "heartbeat_file": "senju/state/missing.json",
        "recovery": {"kind": "workflow_dispatch", "workflow": "x.yml", "ref": "main"},
    })
    plan = build_recovery_plan(registry)
    assert plan["actions"] == []
    assert plan["observations"][0]["reason"] == "provider_not_allowed"


def test_registry_cannot_enable_unknown_installation(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "policy": {
            "unknown_system_installation": "allow",
            "require_owner_authorized": True,
            "same_repository_only": True,
            "allowed_providers": ["github_actions"],
        },
        "workers": [],
    }), encoding="utf-8")
    with pytest.raises(PermissionError, match="deny unknown-system"):
        build_recovery_plan(path)


def test_arbitrary_url_recovery_kind_is_not_accepted(tmp_path: Path) -> None:
    registry = _registry(tmp_path, {
        "id": "webhook-install",
        "owner_authorized": True,
        "provider": "github_actions",
        "heartbeat_file": "senju/state/missing.json",
        "recovery": {"kind": "webhook", "url": "https://example.net/install"},
    })
    plan = build_recovery_plan(registry)
    assert plan["actions"] == []
    assert plan["observations"][0]["reason"] == "unsupported_recovery_kind"
