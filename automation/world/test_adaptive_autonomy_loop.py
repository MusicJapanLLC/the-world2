#!/usr/bin/env python3
"""Comprehensive test suite for THE WORLD autonomy expansion."""

import unittest
from pathlib import Path

from automation.world.adaptive_budget import compute_adaptive_budget, ResourceState
from automation.world.task_dedup import TaskDeduplicator, compute_task_key
from automation.world.experiment_runner import run_experiment
from automation.world.autonomy_orchestrator import AutonomyOrchestrator
from automation.world.autonomy_reporter import generate_autonomy_report, render_markdown, write_report


class TestAdaptiveAutonomyLoop(unittest.TestCase):
    def test_adaptive_budget_scaling(self) -> None:
        high_res = ResourceState(runner_available=16, api_quota_pct=1.0, ci_health_pct=1.0, task_priority="P0")
        budget_high = compute_adaptive_budget("automation/world/", high_res)
        self.assertGreater(budget_high.max_files, 8)
        self.assertGreater(budget_high.max_changed_lines, 1500)

        unauth_budget = compute_adaptive_budget("unauthorized_external_path/", high_res)
        self.assertFalse(unauth_budget.is_authorized_scope)
        self.assertEqual(unauth_budget.max_files, 2)

    def test_task_deduplication(self) -> None:
        state_path = Path("automation/world/test_dedup_tmp.json")
        if state_path.exists():
            state_path.unlink()

        dedup = TaskDeduplicator(state_path)
        is_dup1, key1 = dedup.register_or_check("feat", "Refactor kernel", {"step": 1})
        is_dup2, key2 = dedup.register_or_check("feat", "Refactor kernel", {"step": 1})

        self.assertFalse(is_dup1)
        self.assertTrue(is_dup2)
        self.assertEqual(key1, key2)

        if state_path.exists():
            state_path.unlink()

    def test_experiment_runner(self) -> None:
        def sample_exp():
            return {"metric": 42, "success": True}

        res = run_experiment("test_sample", "automation/world", sample_exp)
        self.assertTrue(res.success)
        self.assertEqual(res.evidence["metric"], 42)

    def test_autonomy_orchestrator_self_repair(self) -> None:
        state_path = Path("automation/world/test_orch_dedup_tmp.json")
        if state_path.exists():
            state_path.unlink()

        dedup = TaskDeduplicator(state_path)
        orch = AutonomyOrchestrator(dedup)

        attempt_count = 0

        def impl():
            return True

        def test():
            nonlocal attempt_count
            return attempt_count > 0

        def repair():
            nonlocal attempt_count
            attempt_count += 1
            return True

        outcome = orch.process_task(
            "bugfix", "Intermittent test failure", {"id": "123"}, impl, test, repair
        )

        self.assertTrue(outcome.shipped)
        self.assertEqual(outcome.repair_attempts, 1)

        if state_path.exists():
            state_path.unlink()

    def test_autonomy_report_generation(self) -> None:
        report = generate_autonomy_report()
        md = render_markdown(report)
        self.assertIn("THE WORLD — Autonomous Expansion Observability Report", md)
        self.assertIn("Active Agents", md)


if __name__ == "__main__":
    unittest.main()
