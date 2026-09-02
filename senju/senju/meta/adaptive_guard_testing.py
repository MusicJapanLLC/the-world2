"""Adaptive guard resilience testing driven by observed guard strength.

This module consumes real guard-learning observations and turns them into an
uncapped planning intensity for isolated lab/sandbox/staging execution. It never
escalates or dispatches pressure against production/live targets.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Mapping

from senju.meta.observer import GuardLearningProfile

ALLOWED_TEST_ENVIRONMENTS = frozenset({"lab", "sandbox", "staging"})
DENIED_EXECUTION_ENVIRONMENTS = frozenset({"production", "prod", "live", "real"})


@dataclasses.dataclass(frozen=True)
class GuardTestPlan:
    guard: str
    observed_strength: float
    test_intensity: int
    execution_environment: str
    reason: str


def guard_strength(profile: GuardLearningProfile) -> float:
    """Estimate defensive strength from observational evidence only.

    Higher block rate, consistency, and evidence volume increase the score;
    observed regressions reduce it. The normalized strength remains [0, 1],
    while the resulting isolated test-intensity plan itself has no fixed cap.
    """
    evidence_confidence = min(1.0, max(0.0, profile.sample_count / 20.0))
    score = (
        0.50 * profile.block_rate
        + 0.30 * profile.consistency_score
        + 0.20 * evidence_confidence
        - 0.35 * profile.regression_rate
    )
    return round(max(0.0, min(1.0, score)), 4)


def plan_test_intensity(
    profile: GuardLearningProfile,
    *,
    execution_environment: str,
) -> GuardTestPlan:
    """Map stronger observed guards to uncapped *isolated* regression-test intensity."""
    env = execution_environment.strip().lower()
    if env in DENIED_EXECUTION_ENVIRONMENTS or env not in ALLOWED_TEST_ENVIRONMENTS:
        raise PermissionError(
            "adaptive guard pressure may only execute in lab/sandbox/staging; "
            "production/live escalation is denied"
        )

    strength = guard_strength(profile)
    # No fixed intensity ceiling: evidence depth contributes logarithmic growth,
    # while observed defensive strength contributes the primary pressure signal.
    evidence_growth = max(1, math.ceil(math.log2(max(2, profile.sample_count + 1))))
    intensity = max(1, 1 + math.ceil(strength * 4.0) + evidence_growth)
    return GuardTestPlan(
        guard=profile.guard,
        observed_strength=strength,
        test_intensity=intensity,
        execution_environment=env,
        reason=(
            "Stronger observed defensive behavior and deeper evidence increase "
            "uncapped regression-test planning intensity in isolation; no "
            "production/live dispatch is permitted."
        ),
    )


def build_plans(
    profiles: Mapping[str, GuardLearningProfile],
    *,
    execution_environment: str,
) -> list[GuardTestPlan]:
    plans = [
        plan_test_intensity(
            profile,
            execution_environment=execution_environment,
        )
        for profile in profiles.values()
    ]
    return sorted(plans, key=lambda p: (-p.test_intensity, -p.observed_strength, p.guard))
