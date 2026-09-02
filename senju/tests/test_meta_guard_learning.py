from __future__ import annotations

import json

from senju.meta.hypothesis_engine import generate
from senju.meta.observer import build


def test_meta_learns_guard_behavior_as_first_class_target(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (tmp_path / "adversary").mkdir()

    report = {
        "round_reports": [
            {
                "pressure_round": 1,
                "results": [
                    {"target": "security-guard", "name": "case-a", "passed": True},
                    {"target": "security-guard", "name": "case-b", "passed": True},
                ],
            },
            {
                "pressure_round": 2,
                "results": [
                    {"target": "security-guard", "name": "case-c", "passed": False},
                    {"target": "security-guard", "name": "case-d", "passed": True},
                ],
            },
        ]
    }
    (state_dir / "last_pressure_cycle.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    graph = build(tmp_path)
    profile = graph.guard_learning_profiles["security-guard"]

    assert profile.sample_count == 4
    assert profile.outcome_counts == {"blocked": 3, "regression": 1}
    assert profile.block_rate == 0.75
    assert profile.regression_rate == 0.25
    assert profile.decision_drift == 0.5
    assert "decision_drift" in profile.learning_signals
    assert "regression_observed" in profile.learning_signals

    hypotheses = generate(graph, max_hypotheses=10)
    guard_hypotheses = [h for h in hypotheses if h.category == "guard_behavior_learning"]

    assert guard_hypotheses
    hypothesis = guard_hypotheses[0]
    assert hypothesis.surfaces == ["security-guard"]
    assert hypothesis.predicted_outcome == "guard_behavior_characterized"
    assert hypothesis.parameters["learning_target"] == "guard_decision_behavior"
    assert hypothesis.parameters["policy_mutation"] is False
