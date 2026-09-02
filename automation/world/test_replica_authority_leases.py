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
        allowed_authority_profiles={"base", "replica-worker"},
        allowed_deploy_targets={"production-noop"},
        replica_authority_profile="replica-worker",
        max_workers=4,
        max_replication_per_run=2,
        max_deploys_per_run=0,
        max_deploys_per_day=0,
    )


def _run(*, replica_authority_fn, state: EvolutionState | None = None):
    state = state or EvolutionState(
        generation=1,
        worker_ids=("META",),
        authority_profile="base",
    )
    return ProductionEvolutionLoop(_envelope()).run(
        state,
        tune_fn=lambda current: {
            "verified": True,
            "requested_replicas": 1,
            "requested_authority_profile": "base",
            "deploy_targets": [],
            "artifact": {},
        },
        replicate_fn=lambda parent, count: ["replica-2"][:count],
        authority_fn=lambda profile: {
            "approved": True,
            "profile": profile,
            "lease_id": "parent-lease",
        },
        replica_authority_fn=replica_authority_fn,
        deploy_fn=lambda target, artifact: {"deployed": False},
        persist_fn=lambda checkpoint: {
            "persisted": True,
            "checkpoint_id": "cp-2",
        },
    )


def test_replica_receives_pre_authorized_profile_lease_automatically() -> None:
    calls = []
    result = _run(
        replica_authority_fn=lambda parent, child, profile: calls.append((parent, child, profile)) or {
            "approved": True,
            "profile": profile,
            "lease_id": "replica-lease-2",
        }
    )

    assert calls == [("META", "replica-2", "replica-worker")]
    assert result.worker_ids == ("META", "replica-2")
    assert result.worker_authority_leases == (("replica-2", "replica-lease-2"),)
    assert result.phase_receipts["replication"]["authority_inherited"] is True
    assert result.phase_receipts["replication"]["replica_authority_profile"] == "replica-worker"


def test_replica_profile_must_be_pre_authorized() -> None:
    with pytest.raises(ProductionEvolutionError, match="replica authority profile must be pre-authorized"):
        ProductionEvolutionEnvelope.create(
            allowed_authority_profiles={"base"},
            allowed_deploy_targets={"production-noop"},
            replica_authority_profile="root",
        )


def test_replica_cannot_receive_different_profile_from_broker() -> None:
    with pytest.raises(ProductionEvolutionError, match="returned a different profile"):
        _run(
            replica_authority_fn=lambda parent, child, profile: {
                "approved": True,
                "profile": "root-unbounded",
                "lease_id": "bad-lease",
            }
        )


def test_replica_profile_requires_explicit_lease_broker() -> None:
    with pytest.raises(ProductionEvolutionError, match="requires replica_authority_fn"):
        _run(replica_authority_fn=None)


def test_existing_replica_leases_survive_next_checkpoint() -> None:
    state = EvolutionState(
        generation=2,
        worker_ids=("META", "replica-1"),
        authority_profile="base",
        worker_authority_leases=(("replica-1", "lease-1"),),
    )
    result = _run(
        state=state,
        replica_authority_fn=lambda parent, child, profile: {
            "approved": True,
            "profile": profile,
            "lease_id": "lease-2",
        },
    )
    assert result.worker_authority_leases == (
        ("replica-1", "lease-1"),
        ("replica-2", "lease-2"),
    )
