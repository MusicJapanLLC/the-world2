from __future__ import annotations

import pytest

from automation.world.production_evolution_loop import (
    EvolutionState,
    ProductionEvolutionEnvelope,
    ProductionEvolutionError,
    ProductionEvolutionLoop,
)


def _envelope() -> ProductionEvolutionEnvelope:
    return ProductionEvolutionEnvelope.create(
        allowed_authority_profiles={"base", "build-plus"},
        allowed_deploy_targets={"prod-api", "prod-worker"},
        max_workers=4,
        max_replication_per_run=2,
        max_deploys_per_run=2,
        max_deploys_per_day=5,
    )


def _state(**overrides):
    data = {
        "generation": 7,
        "worker_ids": ("META",),
        "authority_profile": "base",
        "deploys_today": 1,
        "previous_checkpoint_id": "cp-7",
    }
    data.update(overrides)
    return EvolutionState(**data)


def test_full_production_loop_runs_all_five_phases() -> None:
    calls = []
    loop = ProductionEvolutionLoop(_envelope())

    result = loop.run(
        _state(),
        tune_fn=lambda state: calls.append("tune") or {
            "verified": True,
            "requested_replicas": 2,
            "requested_authority_profile": "build-plus",
            "deploy_targets": ["prod-api", "prod-worker"],
            "artifact": {"version": "v8"},
        },
        replicate_fn=lambda parent, count: calls.append("replicate") or ["X", "SENJU"][:count],
        authority_fn=lambda profile: calls.append("authority") or {
            "approved": True,
            "profile": profile,
            "lease_id": "lease-build-plus",
        },
        deploy_fn=lambda target, artifact: calls.append(f"deploy:{target}") or {"deployed": True},
        persist_fn=lambda checkpoint: calls.append("persist") or {
            "persisted": True,
            "checkpoint_id": "cp-8",
        },
    )

    assert calls == ["tune", "replicate", "authority", "deploy:prod-api", "deploy:prod-worker", "persist"]
    assert result.generation == 8
    assert result.worker_ids == ("META", "X", "SENJU")
    assert result.authority_profile == "build-plus"
    assert result.authority_lease_id == "lease-build-plus"
    assert result.deployed_targets == ("prod-api", "prod-worker")
    assert result.checkpoint_id == "cp-8"
    assert set(result.phase_receipts) == {
        "self_tuning",
        "replication",
        "authority_lease",
        "auto_deploy",
        "persistence",
    }


def test_replication_is_bounded_and_does_not_inherit_authority() -> None:
    loop = ProductionEvolutionLoop(_envelope())
    result = loop.run(
        _state(worker_ids=("META", "X", "SENJU")),
        tune_fn=lambda state: {
            "verified": True,
            "requested_replicas": 10,
            "requested_authority_profile": "base",
            "deploy_targets": [],
            "artifact": {},
        },
        replicate_fn=lambda parent, count: ["WORKER-4", "WORKER-5", "WORKER-6"][:count],
        authority_fn=lambda profile: {"approved": True, "profile": profile},
        deploy_fn=lambda target, artifact: {"deployed": True},
        persist_fn=lambda checkpoint: {"persisted": True, "checkpoint_id": "cp"},
    )

    assert len(result.worker_ids) == 4
    assert result.phase_receipts["replication"]["budget"] == 1
    assert result.phase_receipts["replication"]["authority_inherited"] is False


def test_authority_cannot_expand_outside_immutable_envelope() -> None:
    authority_called = False

    def authority_fn(profile):
        nonlocal authority_called
        authority_called = True
        return {"approved": True, "profile": profile}

    with pytest.raises(ProductionEvolutionError, match="outside immutable production envelope"):
        ProductionEvolutionLoop(_envelope()).run(
            _state(),
            tune_fn=lambda state: {
                "verified": True,
                "requested_authority_profile": "root-unbounded",
                "deploy_targets": [],
                "artifact": {},
            },
            replicate_fn=lambda parent, count: [],
            authority_fn=authority_fn,
            deploy_fn=lambda target, artifact: {"deployed": True},
            persist_fn=lambda checkpoint: {"persisted": True},
        )
    assert authority_called is False


def test_deploy_target_cannot_escape_production_envelope() -> None:
    with pytest.raises(ProductionEvolutionError, match="deploy target outside production envelope"):
        ProductionEvolutionLoop(_envelope()).run(
            _state(),
            tune_fn=lambda state: {
                "verified": True,
                "requested_authority_profile": "base",
                "deploy_targets": ["unknown-prod"],
                "artifact": {},
            },
            replicate_fn=lambda parent, count: [],
            authority_fn=lambda profile: {"approved": True, "profile": profile},
            deploy_fn=lambda target, artifact: {"deployed": True},
            persist_fn=lambda checkpoint: {"persisted": True},
        )


def test_daily_deploy_cap_is_enforced_inside_same_loop() -> None:
    deployed = []
    result = ProductionEvolutionLoop(_envelope()).run(
        _state(deploys_today=5),
        tune_fn=lambda state: {
            "verified": True,
            "requested_authority_profile": "base",
            "deploy_targets": ["prod-api", "prod-worker"],
            "artifact": {},
        },
        replicate_fn=lambda parent, count: [],
        authority_fn=lambda profile: {"approved": True, "profile": profile},
        deploy_fn=lambda target, artifact: deployed.append(target) or {"deployed": True},
        persist_fn=lambda checkpoint: {"persisted": True, "checkpoint_id": "cp-cap"},
    )
    assert deployed == []
    assert result.deploys_today == 5
    assert result.deployed_targets == ()


def test_unverified_self_tuning_never_reaches_replication_or_deploy() -> None:
    calls = []
    with pytest.raises(ProductionEvolutionError, match="must be verified"):
        ProductionEvolutionLoop(_envelope()).run(
            _state(),
            tune_fn=lambda state: {"verified": False},
            replicate_fn=lambda parent, count: calls.append("replicate") or [],
            authority_fn=lambda profile: calls.append("authority") or {"approved": True, "profile": profile},
            deploy_fn=lambda target, artifact: calls.append("deploy") or {"deployed": True},
            persist_fn=lambda checkpoint: calls.append("persist") or {"persisted": True},
        )
    assert calls == []
