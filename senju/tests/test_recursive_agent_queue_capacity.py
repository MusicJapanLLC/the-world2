import pytest

from senju.meta.recursive_agent_broker import (
    MAX_ACTIVE_AGENTS,
    MAX_GENERATION,
    MAX_QUEUED_DESCENDANTS,
    materialize_spawn_request,
    request_descendants,
)


def test_recursive_logical_count_has_no_fixed_ceiling():
    request = request_descendants(
        system="META",
        parent_id="META-CHILD-01",
        parent_generation=1,
        parent_scopes=["read:state", "write:state"],
        desired_count=10**12,
    )
    assert request.desired_count == 10**12
    assert request.queue_limit is None
    assert MAX_QUEUED_DESCENDANTS is None


def test_recursive_generation_has_no_fixed_ceiling():
    request = request_descendants(
        system="X",
        parent_id="X-DEEP-LINEAGE",
        parent_generation=10_000,
        parent_scopes=["read:state"],
        desired_count=10,
    )
    assert request.parent_generation == 10_000
    assert MAX_GENERATION is None

    result = materialize_spawn_request(request, active_agents=49)
    assert len(result.materialized) == 1
    assert result.next_generation == 10_001
    assert result.materialized[0].generation == 10_001
    assert result.materialized[0].may_spawn_children is True


def test_huge_plan_is_deferred_instead_of_materialized_all_at_once():
    desired = 10**12
    request = request_descendants(
        system="X",
        parent_id="X-CHILD-01",
        parent_generation=1,
        parent_scopes=["read:state"],
        desired_count=desired,
    )
    result = materialize_spawn_request(request, active_agents=0)
    assert len(result.materialized) == MAX_ACTIVE_AGENTS
    assert result.deferred_count == desired - MAX_ACTIVE_AGENTS
    assert result.queue_limit is None
    assert all(agent.grant.raw_credential_inherited is False for agent in result.materialized)


def test_descendant_scope_cannot_expand_during_large_request():
    with pytest.raises(PermissionError, match="may not exceed parent scope"):
        request_descendants(
            system="META",
            parent_id="META-CHILD-01",
            parent_generation=1,
            parent_scopes=["read:state"],
            requested_scopes=["read:state", "admin:all"],
            desired_count=10**12,
        )
