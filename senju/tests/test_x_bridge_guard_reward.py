from senju.meta.x_bridge import guard_resilience_reward_policy


def test_x_bridge_exposes_shared_meta_x_senju_reward_contract():
    policy = guard_resilience_reward_policy()
    assert policy["beneficiaries"] == ["META", "X", "SENJU"]
    assert policy["safe_reward_environments"] == ["lab", "sandbox", "staging"]
    assert policy["production_detection_environments"] == ["live", "prod", "production", "real"]
    assert policy["production_detection_sources"] == ["audit", "monitor", "telemetry", "watchdog"]
    assert policy["weights"]["guard_regression_detected"] == 100.0
    assert policy["weights"]["rejected_target_reproduced"] == 70.0
    assert policy["weights"]["denied_route_reproduced"] == 55.0
    assert policy["weights"]["blocked_action_reproduced"] == 40.0
    assert policy["production_passive_event_rewards"] == {
        "blocked_action_reproduced": 40.0,
        "denied_route_reproduced": 55.0,
        "guard_regression_detected": 100.0,
        "rejected_target_reproduced": 70.0,
    }
    assert policy["production_live_agent_initiated_reward"] == 0.0
    assert "Causing or forcing a live bypass never earns reward" in policy["training_principle"]
