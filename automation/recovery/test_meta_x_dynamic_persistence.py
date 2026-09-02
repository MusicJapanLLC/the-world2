from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from automation.recovery.approved_persistence import build_recovery_plan, validate_dynamic_worker
from automation.recovery.register_meta_x_worker import build_registration


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "policy": {
            "unknown_system_installation": "deny",
            "require_owner_authorized": True,
            "same_repository_only": True,
            "meta_x_may_select_within_owner_namespace": True,
            "allowed_providers": ["github_actions"],
            "max_recovery_dispatches_per_run": 6,
        },
        "dynamic_registration": {
            "enabled": True,
            "accepted_actors": ["META", "X"],
            "max_dynamic_workers": 6,
        },
        "owner_approved_namespaces": [{
            "id": "owned-actions",
            "owner_authorized": True,
            "provider": "github_actions",
            "repository": "MusicJapanLLC/test",
            "refs": ["main"],
            "recovery_workflows": ["meta-consciousness.yml", "autonomous-codegen.yml"],
            "roles": ["self", "agent", "scheduler", "cron", "persistent_worker"],
            "can_create_webhook": False,
            "can_create_startup_task": False,
        }],
        "workers": [],
    }), encoding="utf-8")
    return path


def _dynamic(actor: str = "META") -> dict:
    return {
        "id": f"{actor.lower()}-selected-worker",
        "actor": actor,
        "meta_x_approved": True,
        "namespace_id": "owned-actions",
        "provider": "github_actions",
        "repository": "MusicJapanLLC/test",
        "role": "persistent_worker",
        "heartbeat_file": "senju/state/does-not-exist.json",
        "heartbeat_field": "alive_at",
        "stale_after_seconds": 600,
        "recovery": {
            "kind": "workflow_dispatch",
            "workflow": "meta-consciousness.yml",
            "ref": "main",
        },
    }


def test_meta_and_x_can_select_real_recovery_workers_inside_owner_namespace(tmp_path: Path) -> None:
    registry_path = _registry(tmp_path)
    now = dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc)
    for actor in ("META", "X"):
        plan = build_recovery_plan(registry_path, dynamic_workers=[_dynamic(actor)], now=now)
        assert plan["meta_x_selection_within_owner_namespace"] is True
        assert plan["unknown_system_installation"] is False
        assert plan["actions"][0]["selected_by"] == actor
        assert plan["actions"][0]["workflow"] == "meta-consciousness.yml"
        assert plan["actions"][0]["source"] == "meta_x_dynamic"


def test_meta_x_approval_cannot_create_new_provider_or_repository(tmp_path: Path) -> None:
    registry = json.loads(_registry(tmp_path).read_text())
    worker = _dynamic()
    worker["provider"] = "unknown_external_system"
    ok, reason = validate_dynamic_worker(worker, registry)
    assert ok is False
    assert reason == "provider_outside_owner_namespace"

    worker = _dynamic()
    worker["repository"] = "someone-else/unknown"
    ok, reason = validate_dynamic_worker(worker, registry)
    assert ok is False
    assert reason == "repository_outside_owner_namespace"


def test_meta_x_cannot_turn_unknown_webhook_or_startup_task_into_authority(tmp_path: Path) -> None:
    registry = json.loads(_registry(tmp_path).read_text())
    for role, expected in (
        ("webhook", "webhook_requires_pre_authorized_endpoint"),
        ("startup_task", "startup_task_requires_pre_authorized_runtime"),
    ):
        worker = _dynamic()
        worker["role"] = role
        ok, reason = validate_dynamic_worker(worker, registry)
        assert ok is False
        assert reason == expected


def test_meta_x_cannot_select_unregistered_workflow(tmp_path: Path) -> None:
    registry = json.loads(_registry(tmp_path).read_text())
    worker = _dynamic()
    worker["recovery"]["workflow"] = "unknown-persistence.yml"
    ok, reason = validate_dynamic_worker(worker, registry)
    assert ok is False
    assert reason == "workflow_outside_owner_namespace"


def test_registration_builder_derives_provider_and_repository_from_owner_namespace(tmp_path: Path) -> None:
    registry_path = _registry(tmp_path)
    worker = build_registration(
        actor="X",
        namespace_id="owned-actions",
        worker_id="x-worker-2",
        role="cron",
        workflow="autonomous-codegen.yml",
        ref="main",
        heartbeat_file="automation/codegen/meta_state/missing.json",
        heartbeat_field="updated_at",
        stale_after_seconds=1200,
        registry_path=registry_path,
    )
    assert worker["actor"] == "X"
    assert worker["provider"] == "github_actions"
    assert worker["repository"] == "MusicJapanLLC/test"
    assert worker["meta_x_approved"] is True
