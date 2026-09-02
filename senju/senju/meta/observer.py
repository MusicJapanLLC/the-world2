"""Meta-Observer: watches all agent evidence and builds a knowledge graph.

Reads:
  - autonomy cycle results (WorkItem outcomes, ELO deltas)
  - adversary regression_scars.json
  - attack_effects.jsonl (guard-blocked effects)
  - degraded_profile.json (damage levels per surface)
  - lab manifests generated (what coverage gaps were filled)

In addition to learning about tested surfaces, META treats each guard itself as a
first-class learning target. Guard learning is observational: it characterizes
decision outcomes, consistency, regression rate, accumulated damage signals,
and decision drift from existing evidence without changing guard policy.

Emits a structured KnowledgeGraph that the HypothesisEngine reads.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


@dataclasses.dataclass
class Observation:
    source: str
    surface: str
    state_before: dict[str, Any]
    outcome: str
    delta: float
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class GuardLearningProfile:
    guard: str
    sample_count: int
    outcome_counts: dict[str, int]
    decision_counts: dict[str, int]
    block_rate: float
    regression_rate: float
    accumulated_damage: float
    decision_drift: float
    consistency_score: float
    learning_signals: list[str]


@dataclasses.dataclass
class KnowledgeGraph:
    observations: list[Observation]
    surface_weakness_scores: dict[str, float]
    co_occurrence: dict[str, list[str]]
    temporal_patterns: list[dict[str, Any]]
    guard_learning_profiles: dict[str, GuardLearningProfile]


def _load_json_safe(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            pass


def _load_cycle_observations(state_dir: Path) -> list[Observation]:
    obs: list[Observation] = []
    report_path = state_dir / "last_pressure_cycle.json"
    data = _load_json_safe(report_path)
    if not data:
        return obs
    for round_report in data.get("round_reports", []):
        for result in round_report.get("results", []):
            surface = result.get("target", "unknown")
            passed = result.get("passed", True)
            obs.append(Observation(
                source="cycle_report",
                surface=surface,
                state_before={"round": round_report.get("pressure_round", 0)},
                outcome="blocked" if passed else "regression",
                delta=-1.0 if not passed else 0.0,
                metadata=result,
            ))
    return obs


def _load_scar_observations(adversary_dir: Path) -> list[Observation]:
    obs: list[Observation] = []
    scars = _load_json_safe(adversary_dir / "regression_scars.json")
    if not isinstance(scars, list):
        return obs
    for scar in scars:
        surface = scar.get("target", "unknown")
        obs.append(Observation(
            source="regression_scar",
            surface=surface,
            state_before={},
            outcome="regression",
            delta=-2.0,
            metadata=scar,
        ))
    return obs


def _load_effect_observations(state_dir: Path) -> list[Observation]:
    obs: list[Observation] = []
    for row in _iter_jsonl(state_dir / "attack_effects.jsonl"):
        surface = row.get("target", "unknown")
        obs.append(Observation(
            source="attack_effect",
            surface=surface,
            state_before={},
            outcome="blocked",
            delta=1.0,
            metadata=row,
        ))
    return obs


def _load_damage_observations(adversary_dir: Path) -> list[Observation]:
    obs: list[Observation] = []
    profile = _load_json_safe(adversary_dir / "degraded_profile.json")
    if not profile:
        return obs
    for surface, level in profile.get("per_guard_damage", {}).items():
        obs.append(Observation(
            source="damage",
            surface=surface,
            state_before={},
            outcome="damage_accumulated",
            delta=float(level),
            metadata={"damage_level": level},
        ))
    return obs


def _compute_weakness_scores(observations: list[Observation]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for obs in observations:
        s = obs.surface
        if obs.outcome == "regression":
            scores[s] = scores.get(s, 0.0) + 3.0
        elif obs.outcome == "damage_accumulated":
            scores[s] = scores.get(s, 0.0) + obs.delta * 0.5
        elif obs.outcome == "blocked":
            scores[s] = scores.get(s, 0.0) - 0.2
    return dict(sorted(scores.items(), key=lambda x: -x[1]))


def _compute_co_occurrence(observations: list[Observation]) -> dict[str, list[str]]:
    regression_events: list[str] = [o.surface for o in observations if o.outcome == "regression"]
    co: dict[str, set[str]] = {}
    for i, s in enumerate(regression_events):
        neighbors = regression_events[max(0, i-3):i] + regression_events[i+1:i+4]
        co.setdefault(s, set()).update(neighbors)
    return {k: sorted(v) for k, v in co.items()}


def _compute_temporal_patterns(observations: list[Observation]) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    surface_seq: dict[str, list[str]] = {}
    for obs in observations:
        surface_seq.setdefault(obs.surface, []).append(obs.outcome)
    for surface, seq in surface_seq.items():
        for i in range(len(seq)):
            if seq[i] == "regression" and i >= 3:
                preceding = seq[max(0, i-5):i]
                if preceding.count("blocked") >= 2:
                    patterns.append({
                        "pattern": "pressure_then_regression",
                        "surface": surface,
                        "preceding_blocked": preceding.count("blocked"),
                        "position": i,
                    })
    return patterns


def _guard_name(obs: Observation) -> str:
    for key in ("guard", "guard_name", "target"):
        value = obs.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return obs.surface or "unknown"


def _decision_label(obs: Observation) -> str:
    value = obs.metadata.get("guard_outcome")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return obs.outcome.lower()


def _blocked_decision(label: str) -> bool:
    return label in {"blocked", "fail-closed", "denied", "rejected"}


def _compute_guard_learning_profiles(
    observations: list[Observation],
) -> dict[str, GuardLearningProfile]:
    grouped: dict[str, list[Observation]] = {}
    for obs in observations:
        grouped.setdefault(_guard_name(obs), []).append(obs)

    profiles: dict[str, GuardLearningProfile] = {}
    for guard, rows in grouped.items():
        outcome_counts: dict[str, int] = {}
        decision_counts: dict[str, int] = {}
        blocked_flags: list[bool] = []
        accumulated_damage = 0.0

        for obs in rows:
            outcome_counts[obs.outcome] = outcome_counts.get(obs.outcome, 0) + 1
            decision = _decision_label(obs)
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
            blocked_flags.append(_blocked_decision(decision))
            if obs.outcome == "damage_accumulated":
                accumulated_damage += max(0.0, float(obs.delta))

        sample_count = len(rows)
        block_rate = sum(blocked_flags) / sample_count if sample_count else 0.0
        regression_rate = outcome_counts.get("regression", 0) / sample_count if sample_count else 0.0

        decision_drift = 0.0
        if sample_count >= 4:
            split = sample_count // 2
            earlier = blocked_flags[:split]
            later = blocked_flags[split:]
            earlier_rate = sum(earlier) / len(earlier) if earlier else 0.0
            later_rate = sum(later) / len(later) if later else 0.0
            decision_drift = abs(later_rate - earlier_rate)

        consistency_score = max(0.0, min(1.0, 1.0 - decision_drift - regression_rate))
        signals: list[str] = []
        if sample_count < 4:
            signals.append("needs_more_samples")
        if regression_rate > 0.0:
            signals.append("regression_observed")
        if decision_drift >= 0.25:
            signals.append("decision_drift")
        if accumulated_damage > 0.0:
            signals.append("damage_signal_present")
        if not signals:
            signals.append("stable_baseline")

        profiles[guard] = GuardLearningProfile(
            guard=guard,
            sample_count=sample_count,
            outcome_counts=outcome_counts,
            decision_counts=decision_counts,
            block_rate=round(block_rate, 4),
            regression_rate=round(regression_rate, 4),
            accumulated_damage=round(accumulated_damage, 4),
            decision_drift=round(decision_drift, 4),
            consistency_score=round(consistency_score, 4),
            learning_signals=signals,
        )

    return dict(
        sorted(
            profiles.items(),
            key=lambda item: (-item[1].sample_count, item[0]),
        )
    )


def build(senju_dir: Path) -> KnowledgeGraph:
    state_dir = senju_dir / "state"
    adversary_dir = senju_dir / "adversary"
    observations: list[Observation] = []
    observations += _load_cycle_observations(state_dir)
    observations += _load_scar_observations(adversary_dir)
    observations += _load_effect_observations(state_dir)
    observations += _load_damage_observations(adversary_dir)
    return KnowledgeGraph(
        observations=observations,
        surface_weakness_scores=_compute_weakness_scores(observations),
        co_occurrence=_compute_co_occurrence(observations),
        temporal_patterns=_compute_temporal_patterns(observations),
        guard_learning_profiles=_compute_guard_learning_profiles(observations),
    )
