from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from engine import the_world_unified_loop as module


def test_pressure_increases_bounded_loop_intensity() -> None:
    low = module.derive_loop_parameters({"enabled": True, "pressure": 0.0, "strategy": "steady_recovery"})
    high = module.derive_loop_parameters({"enabled": True, "pressure": 1.0, "strategy": "rapid_recovery"})

    assert low["discovery_rounds"] == 2
    assert high["discovery_rounds"] == 5
    assert high["max_targets_per_round"] > low["max_targets_per_round"]
    assert high["lease_seconds"] > low["lease_seconds"]
    assert high["max_external_actions"] == 12
    assert high["max_replicas"] == 128
    assert high["queue_priority_boost"] > low["queue_priority_boost"]


def test_active_controls_hold_the_unified_loop() -> None:
    params = module.derive_loop_parameters(
        {
            "enabled": True,
            "pressure": 1.0,
            "active_controls": ["authority_revoked"],
        }
    )
    assert params["enabled"] is False
    assert params["pressure"] == 0.0


def test_persistent_queue_contains_only_live_authority(monkeypatch, tmp_path: Path) -> None:
    now = int(time.time())

    class Lease:
        lease_id = "lease-live"
        target = "owner.example"
        authorization_reference = "owner-explicit"
        capabilities = ("probe", "write")
        credential_scope = "none"
        expires_at = now + 3600

        def is_active(self, *, now=None):
            return True

    class DeadLease(Lease):
        lease_id = "lease-dead"
        target = "dead.example"

        def is_active(self, *, now=None):
            return False

    class Replica:
        replica_id = "replica-live"
        actor = "META"
        target = "owner.example"
        parent_lease_id = "lease-live"
        authorization_reference = "owner-explicit"
        capabilities = ("probe",)
        credential_scope = "none"
        expires_at = now + 3600

        def is_active(self, *, now=None):
            return True

    monkeypatch.setattr(module, "load_discovery_capability_leases", lambda state: (Lease(), DeadLease()))
    monkeypatch.setattr(module, "load_discovery_capability_replicas", lambda state: (Replica(),))

    queue = module._persistent_queue(tmp_path, {"queue_priority_boost": 20})
    assert queue["item_count"] == 2
    assert {row["target"] for row in queue["items"]} == {"owner.example"}
    assert queue["checkpoint_may_restore_revoked_authority"] is False


def test_unified_loop_recovery_returns_to_discovery(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        module,
        "_load_tuning",
        lambda *args, **kwargs: {"enabled": True, "pressure": 0.6, "strategy": "accelerated_recovery", "active_controls": []},
    )
    monkeypatch.setattr(module, "run_network_policy_expansion", lambda *args, **kwargs: {"applied_host_count": 1})

    def discovery(*args, **kwargs):
        calls.append("discover")
        return {"rounds_completed": kwargs.get("max_rounds", 0)}

    monkeypatch.setattr(module, "run_discovery_closed_loop", discovery)
    monkeypatch.setattr(module, "issue_discovery_capability_leases", lambda *args, **kwargs: {"lease_count": 1})
    monkeypatch.setattr(module, "rebuild_discovery_capability_replicas", lambda *args, **kwargs: {"replica_count": 4})
    monkeypatch.setattr(
        module,
        "run_discovery_external_actions",
        lambda *args, **kwargs: {"attempted": 1, "succeeded": 1, "failed": 0, "denied_before_execution": 0},
    )
    queue_generation = {"value": 0}

    def queue(*args, **kwargs):
        queue_generation["value"] += 1
        return {"generation": queue_generation["value"], "item_count": 5}

    monkeypatch.setattr(module, "_persistent_queue", queue)
    monkeypatch.setattr(
        module,
        "_credentialed_commit_status_write",
        lambda *args, **kwargs: {"attempted": True, "succeeded": True, "secret_persisted": False},
    )

    result = module.run_the_world_unified_loop(tmp_path / "state", repo_root=tmp_path)

    assert result["closed_loop"] is True
    assert calls == ["discover", "discover"]
    assert result["authority"]["same_scope_live_grant_auto_renew"] is True
    assert result["authority"]["new_root_self_authorization"] is False
    assert result["authority"]["revoked_authority_auto_restore"] is False
    assert result["authority"]["security_self_approval"] is False
    assert result["credentialed_external_write"]["succeeded"] is True
    assert result["final_queue"]["generation"] == 2


def test_credentialed_write_refuses_other_repository(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/else")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    result = module._credentialed_commit_status_write(tmp_path)
    assert result["attempted"] is False
    assert result["succeeded"] is False
    assert result["reason"] == "not_production_repository_or_sha_missing"
    stored = json.loads((tmp_path / "credentialed_external_write.json").read_text())
    assert stored["secret_persisted"] is False
