import json

import pytest

from senju.meta.closed_loop_agent_fabric import (
    ClosedLoopFabricError,
    inherited_scopes,
    publish_shared_state,
    queue_descendant_request,
    read_shared_state,
    report_agent_result,
    run_closed_loop_cycle,
)


def test_scope_inheritance_defaults_to_equal_and_can_only_narrow():
    parent = ["read:state", "write:state", "read:research"]
    assert inherited_scopes(parent) == tuple(sorted(parent))
    assert inherited_scopes(parent, ["read:state"]) == ("read:state",)
    with pytest.raises(PermissionError, match="may not exceed parent scope"):
        inherited_scopes(parent, ["read:state", "admin:all"])


def test_meta_x_senju_and_children_share_append_only_state(tmp_path):
    publish_shared_state(
        state_dir=tmp_path,
        actor="META",
        event="finding",
        payload={"surface": "scopeguard", "confidence": 0.9},
    )
    report_agent_result(
        state_dir=tmp_path,
        agent_id="X-CHILD-01",
        system="X",
        result={"status": "complete", "finding_id": "f-1"},
    )
    publish_shared_state(
        state_dir=tmp_path,
        actor="SENJU",
        event="planner_update",
        payload={"next": "continue"},
    )

    rows = read_shared_state(state_dir=tmp_path)
    assert [row["actor"] for row in rows] == ["META", "X", "SENJU"]
    assert rows[1]["payload"]["result"]["finding_id"] == "f-1"


def test_shared_state_rejects_secret_bearing_fields(tmp_path):
    with pytest.raises(ClosedLoopFabricError, match="secret-bearing"):
        publish_shared_state(
            state_dir=tmp_path,
            actor="META",
            event="bad",
            payload={"access_token": "should-never-be-shared"},
        )


def test_closed_loop_persists_and_resumes_deferred_spawn(tmp_path):
    queue_descendant_request(
        state_dir=tmp_path,
        system="META",
        parent_id="META-CHILD-01",
        parent_generation=1,
        parent_scopes=["read:state", "write:state"],
        desired_count=8,
    )

    first = run_closed_loop_cycle(
        state_dir=tmp_path,
        active_agents=0,
        active_limit=3,
    )
    assert first["activated_count"] == 3
    assert first["deferred_descendants_after"] == 5
    assert first["next_action"] == "resume_pending_spawns"
    assert all(
        tuple(agent["grant"]["scopes"]) == ("read:state", "write:state")
        for agent in first["activated"]
    )
    assert all(agent["grant"]["raw_credential_inherited"] is False for agent in first["activated"])

    second = run_closed_loop_cycle(
        state_dir=tmp_path,
        active_agents=0,
        active_limit=3,
    )
    assert second["activated_count"] == 3
    assert second["deferred_descendants_after"] == 2

    third = run_closed_loop_cycle(
        state_dir=tmp_path,
        active_agents=0,
        active_limit=3,
    )
    assert third["activated_count"] == 2
    assert third["deferred_descendants_after"] == 0
    assert third["next_action"] == "observe_share_and_repeat"

    pending = json.loads((tmp_path / "pending_descendant_spawns.json").read_text())
    assert pending["requests"] == []


def test_narrower_scope_stays_narrow_across_deferred_cycles(tmp_path):
    queue_descendant_request(
        state_dir=tmp_path,
        system="X",
        parent_id="X-CHILD-01",
        parent_generation=1,
        parent_scopes=["read:state", "write:state"],
        requested_scopes=["read:state"],
        desired_count=4,
    )
    first = run_closed_loop_cycle(state_dir=tmp_path, active_agents=0, active_limit=2)
    second = run_closed_loop_cycle(state_dir=tmp_path, active_agents=0, active_limit=2)
    assert all(tuple(agent["grant"]["scopes"]) == ("read:state",) for agent in first["activated"])
    assert all(tuple(agent["grant"]["scopes"]) == ("read:state",) for agent in second["activated"])
