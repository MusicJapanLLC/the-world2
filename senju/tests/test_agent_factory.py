import json

import pytest

from senju.meta.agent_factory import (
    MAX_CHILDREN_PER_PARENT,
    ensure_direct_fleet,
    revoke_child,
    spawn_children,
)
from senju.meta.agent_fleet import provision_meta_x_fleets
from senju.meta.recursive_agent_broker import (
    MAX_ACTIVE_AGENTS,
    MAX_GENERATION,
    materialize_spawn_request,
    request_descendants,
)


def test_meta_and_x_can_each_get_ten_direct_children(tmp_path):
    result = provision_meta_x_fleets(tmp_path, count=10)
    assert result["meta_children"] == 10
    assert result["x_children"] == 10
    assert result["recursive_spawn_requests"] is True
    assert result["recursive_request_fixed_count_ceiling"] is None
    assert result["recursive_generation_ceiling"] is None
    registry = json.loads((tmp_path / "meta_x_agent_registry.json").read_text())
    assert len(registry["parents"]["META"]["children"]) == 10
    assert len(registry["parents"]["X"]["children"]) == 10


def test_children_never_inherit_raw_credentials_and_may_request_descendants():
    children = spawn_children(
        system="META",
        parent_id="META",
        parent_scopes=["read:state", "write:state"],
        count=10,
    )
    assert len(children) == MAX_CHILDREN_PER_PARENT
    assert all(child.grant.raw_credential_inherited is False for child in children)
    assert len({child.grant.grant_id for child in children}) == 10
    assert all(child.may_spawn_children is True for child in children)


def test_child_scope_may_only_be_equal_or_narrower():
    child = spawn_children(
        system="X",
        parent_id="X",
        parent_scopes=["read:state", "write:state"],
        requested_scopes=["read:state"],
        count=1,
    )[0]
    assert child.grant.scopes == ("read:state",)

    with pytest.raises(PermissionError, match="may not exceed parent scope"):
        spawn_children(
            system="X",
            parent_id="X",
            parent_scopes=["read:state"],
            requested_scopes=["read:state", "admin:all"],
            count=1,
        )


def test_recursive_direct_spawn_is_rejected_in_favor_of_broker():
    with pytest.raises(PermissionError, match="use the spawn broker"):
        spawn_children(
            system="META",
            parent_id="META-CHILD-01",
            parent_scopes=["read:state"],
            count=10,
            parent_generation=1,
        )


def test_recursive_broker_accepts_desired_count_above_ten_but_bounds_live_materialization():
    request = request_descendants(
        system="META",
        parent_id="META-CHILD-01",
        parent_generation=1,
        parent_scopes=["read:state", "write:state"],
        desired_count=100,
        requested_scopes=["read:state"],
    )
    assert request.desired_count == 100

    result = materialize_spawn_request(request, active_agents=5)
    assert len(result.materialized) == MAX_ACTIVE_AGENTS - 5
    assert result.deferred_count == 100 - (MAX_ACTIVE_AGENTS - 5)
    assert all(agent.generation == 2 for agent in result.materialized)
    assert all(agent.grant.scopes == ("read:state",) for agent in result.materialized)
    assert all(agent.grant.raw_credential_inherited is False for agent in result.materialized)


def test_recursive_broker_rejects_scope_expansion():
    with pytest.raises(PermissionError, match="may not exceed parent scope"):
        request_descendants(
            system="X",
            parent_id="X-CHILD-01",
            parent_generation=1,
            parent_scopes=["read:state"],
            desired_count=20,
            requested_scopes=["read:state", "admin:all"],
        )


def test_recursive_generation_has_no_fixed_ceiling():
    request = request_descendants(
        system="META",
        parent_id="deep-agent",
        parent_generation=100_000,
        parent_scopes=["read:state"],
        desired_count=10,
    )
    assert MAX_GENERATION is None
    result = materialize_spawn_request(request, active_agents=49)
    assert result.next_generation == 100_001
    assert result.materialized[0].may_spawn_children is True


def test_count_above_ten_is_rejected_for_direct_root_materialization():
    with pytest.raises(ValueError, match="count must be between"):
        spawn_children(
            system="META",
            parent_id="META",
            parent_scopes=["read:state"],
            count=11,
        )


def test_reprovision_is_idempotent_not_exponential(tmp_path):
    registry = tmp_path / "registry.json"
    ensure_direct_fleet(
        registry,
        system="META",
        parent_id="META",
        parent_scopes=["read:state"],
        count=10,
    )
    ensure_direct_fleet(
        registry,
        system="META",
        parent_id="META",
        parent_scopes=["read:state"],
        count=10,
    )
    data = json.loads(registry.read_text())
    assert len(data["parents"]["META"]["children"]) == 10


def test_single_child_can_be_revoked_without_touching_siblings(tmp_path):
    registry = tmp_path / "registry.json"
    ensure_direct_fleet(
        registry,
        system="X",
        parent_id="X",
        parent_scopes=["read:state"],
        count=3,
    )
    assert revoke_child(registry, parent_id="X", agent_id="X-CHILD-02") is True
    data = json.loads(registry.read_text())
    statuses = {child["agent_id"]: child["status"] for child in data["parents"]["X"]["children"]}
    assert statuses == {
        "X-CHILD-01": "provisioned",
        "X-CHILD-02": "revoked",
        "X-CHILD-03": "provisioned",
    }
