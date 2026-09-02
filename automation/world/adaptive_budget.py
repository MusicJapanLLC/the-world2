#!/usr/bin/env python3
"""Adaptive resource-aware dynamic budgeting for THE WORLD.

Replaces fixed low ceilings with dynamic budgets based on runner availability,
API quota, DB load, CI health, failure rates, and task priority/value.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

BASE_MAX_FILES = 8
BASE_MAX_CHANGED_LINES = 1500
BASE_CONCURRENCY = 4
BASE_RETRIES = 2
BASE_CHILD_DEPTH = 3
BASE_RESEARCH_FANOUT = 5

ALLOWED_OWNED_SCOPES = (
    "automation/",
    "senju/",
    "company-society/",
    "value-lab/",
    "outside-world/",
    "tomoki-agents/",
    "standment-security/",
    "docs/",
    "src/",
    "scripts/",
)


@dataclass
class ResourceState:
    runner_available: int = 4
    api_quota_pct: float = 1.0
    db_load_pct: float = 0.2
    ci_health_pct: float = 0.95
    recent_failure_rate: float = 0.05
    task_priority: str = "P1"  # P0, P1, P2


@dataclass
class AdaptiveBudget:
    max_files: int
    max_changed_lines: int
    max_concurrency: int
    max_retries: int
    max_child_depth: int
    research_fanout: int
    is_authorized_scope: bool
    scale_factor: float
    reason: str


def compute_adaptive_budget(
    scope_path: str = "",
    resource_state: ResourceState | None = None,
    base_files: int = BASE_MAX_FILES,
    base_lines: int = BASE_MAX_CHANGED_LINES,
) -> AdaptiveBudget:
    state = resource_state or ResourceState()

    # Determine scope authorization
    is_authorized = True
    if scope_path:
        clean_path = scope_path.replace("\\", "/")
        is_authorized = any(clean_path.startswith(prefix) for prefix in ALLOWED_OWNED_SCOPES) or clean_path.startswith("./")

    # Priority weight multiplier
    priority_mult = {"P0": 2.5, "P1": 1.5, "P2": 1.0}.get(state.task_priority.upper(), 1.0)

    # Health multiplier based on failure rate and CI health
    health_mult = max(0.4, state.ci_health_pct * (1.0 - state.recent_failure_rate * 1.5))

    # Quota and load multiplier
    capacity_mult = max(0.3, state.api_quota_pct * (1.0 - min(0.9, state.db_load_pct)))

    # Combined scale factor
    scale = max(0.5, min(6.0, priority_mult * health_mult * capacity_mult))

    if not is_authorized:
        # Restricted external scope budget
        return AdaptiveBudget(
            max_files=min(2, base_files),
            max_changed_lines=min(200, base_lines),
            max_concurrency=1,
            max_retries=1,
            max_child_depth=1,
            research_fanout=1,
            is_authorized_scope=False,
            scale_factor=0.2,
            reason="Unauthorized or external scope restricts budget",
        )

    max_files = int(base_files * scale)
    max_lines = int(base_lines * scale)
    max_concurrency = max(1, min(16, int(BASE_CONCURRENCY * scale)))
    max_retries = max(1, min(6, int(BASE_RETRIES * scale)))
    max_child_depth = max(1, min(5, int(BASE_CHILD_DEPTH * scale)))
    research_fanout = max(2, min(12, int(BASE_RESEARCH_FANOUT * scale)))

    reason = f"Adaptive budget scaled by {scale:.2f}x (runners={state.runner_available}, quota={state.api_quota_pct*100:.0f}%, CI={state.ci_health_pct*100:.0f}%)"

    return AdaptiveBudget(
        max_files=max_files,
        max_changed_lines=max_lines,
        max_concurrency=max_concurrency,
        max_retries=max_retries,
        max_child_depth=max_child_depth,
        research_fanout=research_fanout,
        is_authorized_scope=True,
        scale_factor=round(scale, 2),
        reason=reason,
    )


if __name__ == "__main__":
    budget = compute_adaptive_budget("automation/world/")
    print(asdict(budget))
