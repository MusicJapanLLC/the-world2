#!/usr/bin/env python3
"""Regression contract for THE WORLD's self-sustaining autonomy loop.

This does not claim literal infinite uptime. It prevents accidental removal of
independent heartbeat, recovery, provider-independent research, memory restore,
and anti-stagnation mechanisms that keep the system autonomous under ordinary
GitHub/service failures.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PerpetualAutonomyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = json.loads((ROOT / "automation/world/realtime_plan.json").read_text(encoding="utf-8"))
        self.workers = {row["workflow"]: row for row in self.plan["workers"]}

    def test_realtime_kernel_owns_new_security_and_research_workers(self) -> None:
        required = {
            "security-continuous-whitehat.yml": 18,
            "ai-dev-minute-foundry.yml": 72,
            "standment-ai-security-eval.yml": 80,
            "the-world-autonomous-research-fabric.yml": 35,
            "the-world-agent-factory.yml": 300,
            "standment-whitehat-portfolio-cycle.yml": 1560,
            "standment-security-portfolio-rnd.yml": 1560,
            "standment-security-portfolio-foundry.yml": 1560,
        }
        for workflow, max_stale in required.items():
            self.assertIn(workflow, self.workers)
            row = self.workers[workflow]
            self.assertTrue(row.get("autostart"), workflow)
            self.assertLessEqual(int(row["stale_minutes"]), max_stale, workflow)

        self.assertEqual(self.plan["repair_workflow"], "tomoki-forge.yml")
        self.assertEqual(int(self.plan["repair_after_attempts"]), 1)
        self.assertGreaterEqual(int(self.plan["max_dispatches_per_pulse"]), 8)

    def test_ai_and_security_are_top_priority_collaboration_lanes(self) -> None:
        ordered = sorted(self.plan["workers"], key=lambda row: int(row.get("priority", 0)), reverse=True)
        top_four = [row["workflow"] for row in ordered[:4]]
        self.assertEqual(
            top_four,
            [
                "ai-security-joint-lab.yml",
                "security-continuous-whitehat.yml",
                "ai-dev-minute-foundry.yml",
                "standment-ai-security-eval.yml",
            ],
        )
        self.assertLessEqual(int(self.workers["ai-security-joint-lab.yml"]["director_min_interval_minutes"]), 10)
        self.assertLessEqual(int(self.workers["security-continuous-whitehat.yml"]["director_min_interval_minutes"]), 5)
        self.assertLessEqual(int(self.workers["ai-dev-minute-foundry.yml"]["director_min_interval_minutes"]), 60)
        self.assertLessEqual(int(self.workers["standment-ai-security-eval.yml"]["director_min_interval_minutes"]), 60)

    def test_realtime_kernel_runs_every_five_minutes_and_can_recover(self) -> None:
        text = (ROOT / ".github/workflows/the-world-realtime-kernel.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '*/5 * * * *'", text)
        self.assertIn("actions: write", text)
        self.assertIn("--apply", text)
        self.assertIn("test_perpetual_autonomy", text)

    def test_provider_independent_research_path_remains_alive(self) -> None:
        # Agent Factory may depend on a model/provider. Research Fabric and the
        # local White-Hat path must remain separately scheduled and supervised.
        fabric = (ROOT / ".github/workflows/the-world-autonomous-research-fabric.yml").read_text(encoding="utf-8")
        whitehat = (ROOT / ".github/workflows/security-continuous-whitehat.yml").read_text(encoding="utf-8")
        agent_factory = (ROOT / ".github/workflows/the-world-agent-factory.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '*/15 * * * *'", fabric)
        self.assertIn("record-research", fabric)
        self.assertIn("cron: '*/5 * * * *'", whitehat)
        self.assertIn("rounds=12", whitehat)
        self.assertIn("seq 1 \"$rounds\"", whitehat)
        self.assertIn("Copilot", agent_factory)
        self.assertTrue(self.workers["the-world-autonomous-research-fabric.yml"]["autostart"])
        self.assertTrue(self.workers["security-continuous-whitehat.yml"]["autostart"])

    def test_ai_security_assist_contract_is_not_removed(self) -> None:
        ai = (ROOT / ".github/workflows/ai-dev-minute-foundry.yml").read_text(encoding="utf-8")
        security = (ROOT / ".github/workflows/security-continuous-whitehat.yml").read_text(encoding="utf-8")
        evaluator = (ROOT / ".github/workflows/standment-ai-security-eval.yml").read_text(encoding="utf-8")
        self.assertIn("Load latest Security R&D assist evidence", ai)
        self.assertIn("--rounds \"$rounds\"", ai)
        self.assertIn("rounds=9", ai)
        self.assertIn("rounds=36", ai)
        self.assertIn("Load latest AI Foundry assist evidence", security)
        self.assertIn("ai_assist_source_run", security)
        self.assertIn("cron: '35 * * * *'", evaluator)
        self.assertIn("Load AI + Security collaboration evidence", evaluator)
        self.assertIn("collaboration-context.json", evaluator)

    def test_portfolio_memory_and_stagnation_escape_are_not_removed(self) -> None:
        rnd = (ROOT / ".github/workflows/standment-security-portfolio-rnd.yml").read_text(encoding="utf-8")
        planner = (ROOT / "automation/security/portfolio_rnd.py").read_text(encoding="utf-8")
        self.assertIn("Restore previous successful portfolio R&D memory", rnd)
        self.assertIn("PREVIOUS_RND_STATE", rnd)
        self.assertIn("stagnation_streak", planner)
        self.assertIn("SWITCH_EVIDENCE_PATH", planner)
        self.assertIn("REFRAME_AND_COUNTEREVIDENCE", planner)


if __name__ == "__main__":
    unittest.main()
