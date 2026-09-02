import json
import tempfile
import unittest
from pathlib import Path

from scripts import guard_pressure_learning as gpl


class GuardPressureLearningTests(unittest.TestCase):
    def test_aggregate_keeps_counts_not_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "one.json").write_text(json.dumps({
                "schema": "scopeguard-fuzz-evidence/v1",
                "seed": 11,
                "stats": {"cases": 1000, "allowed": 100, "rejected": 900, "unexpected": 0},
                "payload": "https://should-not-survive.example/path",
            }), encoding="utf-8")
            report = gpl.aggregate(root)
            self.assertEqual(1000, report["fuzz"]["cases"])
            self.assertEqual(1, report["fuzz"]["seed_count"])
            text = json.dumps(report).lower()
            self.assertNotIn("should-not-survive", text)
            self.assertEqual("none", report["execution_authority"])

    def test_unexpected_changes_research_posture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "one.json").write_text(json.dumps({
                "schema": "scopeguard-fuzz-evidence/v1",
                "seed": 1,
                "stats": {"cases": 10, "allowed": 1, "rejected": 8, "unexpected": 1},
            }), encoding="utf-8")
            report = gpl.aggregate(root)
            self.assertEqual("investigate-unexpected-guard-behaviour", report["research_posture"])

    def test_hypothesis_context_is_bounded(self):
        report = {
            "fuzz": {"cases": 10_000_000, "seed_count": 10, "unexpected": 0},
            "pressure_surfaces": [{"surface": "family:public-mutation", "cases": 100, "surprises": 0}],
            "research_posture": "expand-offline-boundary-diversity",
        }
        text = gpl.hypothesis_context(report)
        self.assertLessEqual(len(text), 520)
        self.assertIn("10000000", text)


if __name__ == "__main__":
    unittest.main()
