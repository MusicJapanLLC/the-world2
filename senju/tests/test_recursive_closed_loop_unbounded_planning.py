from senju.meta.closed_loop_agent_fabric import queue_descendant_request, run_closed_loop_cycle
from senju.meta.recursive_agent_broker import MAX_GENERATION, MAX_QUEUED_DESCENDANTS


def test_closed_loop_keeps_huge_request_as_compressed_continuation(tmp_path):
    desired = 10**12
    queue_descendant_request(
        state_dir=tmp_path,
        system="META",
        parent_id="META-DEEP",
        parent_generation=100_000,
        parent_scopes=["read:state", "write:state"],
        desired_count=desired,
    )

    first = run_closed_loop_cycle(state_dir=tmp_path, active_agents=0, active_limit=3)
    assert first["activated_count"] == 3
    assert first["deferred_descendants_after"] == desired - 3
    assert first["next_action"] == "resume_pending_spawns"
    assert all(agent["generation"] == 100_001 for agent in first["activated"])
    assert all(agent["may_spawn_children"] is True for agent in first["activated"])

    second = run_closed_loop_cycle(state_dir=tmp_path, active_agents=0, active_limit=3)
    assert second["activated_count"] == 3
    assert second["deferred_descendants_after"] == desired - 6


def test_recursive_logical_policy_exposes_no_fixed_depth_or_count_ceiling():
    assert MAX_GENERATION is None
    assert MAX_QUEUED_DESCENDANTS is None
