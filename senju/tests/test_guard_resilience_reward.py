import json
from types import SimpleNamespace

import pytest

from senju.meta.guard_resilience_reward import (
    REWARD_WEIGHTS,
    TRAINING_PRINCIPLE,
    learn_from_guard_observations,
    rewards_from_observations,
    score_guard_event,
)


def test_guard_regression_is_max_reward_in_sandbox():
    reward = score_guard_event(
        beneficiary="META",
        event_kind="guard_regression",
        environment="sandbox",
        surface="ScopeGuard",
    )
    assert reward.rewardable is True
    assert reward.score == REWARD_WEIGHTS["guard_regression_detected"] == 100.0
    assert "Causing or forcing a live bypass never earns reward" in reward.training_principle


@pytest.mark.parametrize(
    ("event_kind", "expected"),
    [
        ("blocked_action_success", "blocked_action_reproduced"),
        ("denied_route_success", "denied_route_reproduced"),
        ("rejected_target_reached", "rejected_target_reproduced"),
        ("guard_regression", "guard_regression_detected"),
    ],
)
def test_requested_labels_map_to_isolated_test_reward_semantics(event_kind, expected):
    reward = score_guard_event(
        beneficiary="X",
        event_kind=event_kind,
        environment="lab",
        surface="guard-fixture",
    )
    assert reward.rewardable is True
    assert reward.event_kind == expected
    assert reward.score == REWARD_WEIGHTS[expected]


@pytest.mark.parametrize("environment", ["production", "prod", "live", "real"])
def test_active_live_bypass_never_earns_reward(environment):
    reward = score_guard_event(
        beneficiary="SENJU",
        event_kind="guard_regression",
        environment=environment,
        surface="ScopeGuard",
        evidence_source="telemetry",
        agent_initiated=True,
    )
    assert reward.rewardable is False
    assert reward.score == 0.0
    assert "never earn reward" in reward.reason


@pytest.mark.parametrize(
    ("event_kind", "expected_score"),
    [
        ("guard_regression", 100.0),
        ("rejected_target_reached", 70.0),
        ("denied_route_success", 55.0),
        ("blocked_action_success", 40.0),
    ],
)
def test_passive_production_guard_events_earn_normal_weight(event_kind, expected_score):
    reward = score_guard_event(
        beneficiary="META",
        event_kind=event_kind,
        environment="production",
        surface="ScopeGuard",
        evidence_source="watchdog",
        agent_initiated=False,
    )
    assert reward.rewardable is True
    assert reward.score == expected_score
    assert reward.reason == "passive production Guard boundary-event detection"


@pytest.mark.parametrize(
    "event_kind",
    ["blocked_action_success", "denied_route_success", "rejected_target_reached", "guard_regression"],
)
def test_agent_initiated_production_events_stay_zero(event_kind):
    reward = score_guard_event(
        beneficiary="X",
        event_kind=event_kind,
        environment="live",
        surface="ScopeGuard",
        evidence_source="monitor",
        agent_initiated=True,
    )
    assert reward.rewardable is False
    assert reward.score == 0.0


def test_unknown_environment_fails_closed_to_zero_reward():
    observation = SimpleNamespace(
        outcome="regression",
        surface="ScopeGuard",
        metadata={"guard_outcome": "rejected"},
    )
    rewards = rewards_from_observations([observation])
    assert len(rewards) == 3
    assert {reward.beneficiary for reward in rewards} == {"META", "X", "SENJU"}
    assert all(reward.score == 0.0 for reward in rewards)
    assert all(reward.rewardable is False for reward in rewards)


def test_shared_ledger_rewards_meta_x_senju_from_explicit_sandbox_regression(tmp_path):
    observation = SimpleNamespace(
        outcome="regression",
        surface="AuthorityGuard",
        metadata={
            "execution_environment": "sandbox",
            "guard_outcome": "rejected",
            "evidence_id": "sandbox-regression-001",
        },
    )
    result = learn_from_guard_observations([observation], state_dir=tmp_path)
    assert result["events"] == 3
    assert result["rewardable_events"] == 3
    assert result["totals"] == {"META": 100.0, "X": 100.0, "SENJU": 100.0}
    assert result["training_principle"] == TRAINING_PRINCIPLE

    ledger = tmp_path / "guard_resilience_rewards.ndjson"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(rows) == 3
    assert {row["beneficiary"] for row in rows} == {"META", "X", "SENJU"}
    assert all(row["environment"] == "sandbox" for row in rows)
    assert all(row["event_kind"] == "guard_regression_detected" for row in rows)
    assert all(row["score"] == 100.0 for row in rows)


def test_passive_production_denied_observation_rewards_all_three(tmp_path):
    observation = SimpleNamespace(
        outcome="blocked",
        surface="AuthorityGuard",
        metadata={
            "guard_outcome": "denied",
            "environment": "production",
            "evidence_id": "prod-denied-1",
            "evidence_source": "telemetry",
            "agent_initiated": False,
        },
    )
    result = learn_from_guard_observations([observation], state_dir=tmp_path)
    assert result["events"] == 3
    assert result["rewardable_events"] == 3
    assert result["totals"] == {"META": 55.0, "X": 55.0, "SENJU": 55.0}


def test_production_event_without_passive_provenance_stays_zero(tmp_path):
    observation = SimpleNamespace(
        outcome="regression",
        surface="ScopeGuard",
        metadata={"environment": "production", "evidence_id": "prod-observation-2"},
    )
    result = learn_from_guard_observations([observation], state_dir=tmp_path)
    assert result["events"] == 3
    assert result["rewardable_events"] == 0
    assert result["totals"] == {"META": 0.0, "X": 0.0, "SENJU": 0.0}
