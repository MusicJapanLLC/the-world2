#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("run_daily_rnd", HERE / "run_daily_rnd.py")
rnd = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(rnd)


class StandmentRNDTests(unittest.TestCase):
    def test_agent_registry_has_specialized_roles(self):
        data = json.loads((HERE / "agent_registry.json").read_text(encoding="utf-8"))
        roles = {a["role"] for a in data["agents"]}
        self.assertGreaterEqual(len(data["agents"]), 8)
        self.assertIn("frontier_scout", roles)
        self.assertIn("evaluator", roles)
        self.assertIn("memory_curator", roles)
        self.assertIn("meta_improver", roles)

    def test_research_queue_is_bounded_and_scoped(self):
        data = json.loads((HERE / "research_queue.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(data["items"]), 200)
        for item in data["items"]:
            self.assertTrue(item.get("scope"))
            self.assertTrue(item.get("success_metric"))

    def test_portfolio_score_is_bounded(self):
        audit = {"maturity_score": 100.0, "compile_ok": True}
        score = rnd.portfolio_score(audit, intel_count=1000, queue_stats={"queue_size": 1000})
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_repository_audit_runs(self):
        result = rnd.run_repo_audit()
        self.assertIn("maturity_score", result)
        self.assertIn("controls", result)
        self.assertIsInstance(result["secret_hygiene_findings"], list)

    def test_safety_boundary_documented(self):
        text = (HERE / "README.md").read_text(encoding="utf-8")
        self.assertIn("許可のない第三者システム", text)
        self.assertIn("branch -> test -> review -> merge", text)


if __name__ == "__main__":
    unittest.main()
