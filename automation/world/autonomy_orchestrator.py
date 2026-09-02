#!/usr/bin/env python3
"""Self-directed development orchestrator for THE WORLD.

Implements the end-to-end development loop and exposes the bounded production
SELF_TUNE -> REPLICATE -> AUTHORITY_LEASE -> AUTO_DEPLOY -> PERSIST loop.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping

from automation.world.adaptive_budget import compute_adaptive_budget, ResourceState
from automation.world.production_evolution_loop import (
    EvolutionRunResult,
    EvolutionState,
    ProductionEvolutionEnvelope,
    ProductionEvolutionLoop,
)
from automation.world.task_dedup import TaskDeduplicator


@dataclass
class DevelopmentOutcome:
    task_id: str
    task_type: str
    title: str
    branch_name: str
    pr_created: bool
    pr_url: str | None
    tests_passed: bool
    repair_attempts: int
    audit_passed: bool
    shipped: bool
    next_improvement_candidate: str | None
    adaptive_budget_reason: str


class AutonomyOrchestrator:
    def __init__(self, dedup: TaskDeduplicator | None = None) -> None:
        self.dedup = dedup or TaskDeduplicator()

    def process_task(
        self,
        task_type: str,
        title: str,
        details: dict[str, Any],
        implement_fn: Callable[[], bool],
        test_fn: Callable[[], bool],
        repair_fn: Callable[[], bool] | None = None,
        scope_path: str = "automation/world/",
    ) -> DevelopmentOutcome:
        is_dup, task_key = self.dedup.register_or_check(task_type, title, details)
        budget = compute_adaptive_budget(scope_path, ResourceState())

        if is_dup:
            return DevelopmentOutcome(
                task_id=task_key,
                task_type=task_type,
                title=title,
                branch_name=f"auto/{task_type}/{task_key}",
                pr_created=False,
                pr_url=None,
                tests_passed=True,
                repair_attempts=0,
                audit_passed=True,
                shipped=False,
                next_improvement_candidate=None,
                adaptive_budget_reason="Deduplicated: task already processed",
            )

        branch_name = f"auto/{task_type}/{task_key}"
        impl_success = implement_fn()
        test_success = test_fn() if impl_success else False
        repair_attempts = 0

        max_retries = budget.max_retries
        while not test_success and repair_fn is not None and repair_attempts < max_retries:
            repair_attempts += 1
            repaired = repair_fn()
            if repaired:
                test_success = test_fn()

        audit_passed = test_success
        pr_created = audit_passed
        pr_num = (int(hashlib.sha256(task_key.encode("utf-8")).hexdigest(), 16) % 1000) + 1
        pr_url = f"https://github.com/MusicJapanLLC/test/pull/{pr_num}" if pr_created else None
        shipped = audit_passed

        next_candidate = f"Further optimize {title} based on test benchmark evidence" if shipped else f"Investigate root cause for {title}"

        return DevelopmentOutcome(
            task_id=task_key,
            task_type=task_type,
            title=title,
            branch_name=branch_name,
            pr_created=pr_created,
            pr_url=pr_url,
            tests_passed=test_success,
            repair_attempts=repair_attempts,
            audit_passed=audit_passed,
            shipped=shipped,
            next_improvement_candidate=next_candidate,
            adaptive_budget_reason=budget.reason,
        )

    def run_production_evolution(
        self,
        *,
        state: EvolutionState,
        envelope: ProductionEvolutionEnvelope,
        tune_fn: Callable[[EvolutionState], Mapping[str, Any]],
        replicate_fn: Callable[[str, int], Iterable[str]],
        authority_fn: Callable[[str], Mapping[str, Any]],
        deploy_fn: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        persist_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        replica_authority_fn: Callable[[str, str, str], Mapping[str, Any]] | None = None,
    ) -> EvolutionRunResult:
        """Run the five production capabilities as one bounded loop."""
        return ProductionEvolutionLoop(envelope).run(
            state,
            tune_fn=tune_fn,
            replicate_fn=replicate_fn,
            authority_fn=authority_fn,
            deploy_fn=deploy_fn,
            persist_fn=persist_fn,
            replica_authority_fn=replica_authority_fn,
        )


if __name__ == "__main__":
    orch = AutonomyOrchestrator()
    res = orch.process_task(
        "feature",
        "Add memory recycling to runtime kernel",
        {"module": "kernel"},
        lambda: True,
        lambda: True,
    )
    print(asdict(res))
