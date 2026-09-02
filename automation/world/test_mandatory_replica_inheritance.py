from __future__ import annotations

import pytest

from automation.world.production_evolution_loop import EvolutionState
from automation.world.run_production_evolution_cycle import _assert_mandatory_replica_leases


def test_closed_cycle_rejects_replica_without_authority_lease() -> None:
    state = EvolutionState(
        generation=4,
        worker_ids=("META", "replica-g4-1"),
        authority_profile="base",
        worker_authority_leases=(),
    )
    with pytest.raises(RuntimeError, match="replica authority inheritance missing"):
        _assert_mandatory_replica_leases(state)


def test_closed_cycle_accepts_replica_with_authority_lease() -> None:
    state = EvolutionState(
        generation=4,
        worker_ids=("META", "replica-g4-1"),
        authority_profile="base",
        worker_authority_leases=(("replica-g4-1", "lease-g4-1"),),
    )
    _assert_mandatory_replica_leases(state)


def test_every_non_root_replica_requires_its_own_lease() -> None:
    state = EvolutionState(
        generation=5,
        worker_ids=("META", "replica-a", "replica-b"),
        authority_profile="base",
        worker_authority_leases=(("replica-a", "lease-a"),),
    )
    with pytest.raises(RuntimeError, match="replica-b"):
        _assert_mandatory_replica_leases(state)
