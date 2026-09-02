from __future__ import annotations

import pytest

from scripts.apply_covenant_intent import BOUNDS, apply_intent


BASE = {
    "population": 100,
    "generations": 10,
    "matches": 300,
    "mutation_rate": 0.15,
    "red_budget": 12,
    "blue_budget": 12,
    "seed": 42,
}


def covenant(*modes: str, manager: bool = False, boss: bool = False):
    return {
        "schema": "covenant-autonomy-plan/v2",
        "generated_at": "2026-08-30T00:00:00+00:00",
        "principle": "bounded autonomy",
        "plans": [
            {"worker": f"senju-{i}", "mode": mode}
            for i, mode in enumerate(modes)
        ],
        "sanctuary": [],
        "fellowship_requests": [],
        "gratitude": [],
        "manager_attention": manager,
        "boss_attention": boss,
    }


def live_ok():
    return {
        "coupling": {
            "real_external_observation": True,
            "observation_influences_arena_target": True,
        },
        "observation": {"provider_acknowledged": True},
    }


def assert_bounded(result):
    assert set(result) == set(BOUNDS)
    for key, (lo, hi) in BOUNDS.items():
        assert lo <= float(result[key]) <= hi


def test_act_plus_reality_increases_exploration_without_new_surface():
    result, audit = apply_intent(BASE, covenant("ACT", "ACT"), live_ok())
    assert audit["intent_mode"] == "EXPLORE_HARD"
    assert audit["candidate_count"] == 9
    assert result["matches"] > BASE["matches"]
    assert result["mutation_rate"] > BASE["mutation_rate"]
    assert_bounded(result)


def test_missing_reality_forces_deeper_verification():
    result, audit = apply_intent(BASE, covenant("ACT"), None)
    assert audit["intent_mode"] == "VERIFY_DEEPLY"
    assert audit["reality_signal"] is False
    assert result["matches"] > BASE["matches"]
    assert result["mutation_rate"] < BASE["mutation_rate"]
    assert_bounded(result)


def test_sanctuary_reduces_exploration_pressure():
    result, audit = apply_intent(BASE, covenant("SANCTUARY"), live_ok())
    assert audit["intent_mode"] == "STABILIZE"
    assert audit["candidate_count"] == 3
    assert result["population"] < BASE["population"]
    assert result["mutation_rate"] < BASE["mutation_rate"]
    assert_bounded(result)


def test_boss_attention_also_stabilizes_even_when_acting():
    result, audit = apply_intent(BASE, covenant("ACT", boss=True), live_ok())
    assert audit["intent_mode"] == "STABILIZE"
    assert result["mutation_rate"] < BASE["mutation_rate"]
    assert_bounded(result)


def test_pair_balances_red_blue_budgets():
    base = dict(BASE, red_budget=18, blue_budget=8)
    result, audit = apply_intent(base, covenant("PAIR"), live_ok())
    assert audit["intent_mode"] == "COLLABORATE"
    assert result["red_budget"] == result["blue_budget"]
    assert_bounded(result)


def test_rejects_hidden_top_level_control_fields():
    plan = covenant("ACT")
    plan["external_command"] = "do something"
    with pytest.raises(ValueError, match="unexpected covenant fields"):
        apply_intent(BASE, plan, live_ok())


def test_rejects_strategy_surface_expansion():
    strategy = dict(BASE)
    strategy["extra"] = 1
    with pytest.raises(ValueError, match="strategy surface mismatch"):
        apply_intent(strategy, covenant("ACT"), live_ok())
