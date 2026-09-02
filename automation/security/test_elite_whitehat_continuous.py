import json
import tempfile
import unittest
from pathlib import Path

import elite_whitehat_continuous as worker


class EliteWhiteHatContinuousTests(unittest.TestCase):
    def _fixture(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "standment-security").mkdir(parents=True)
        (root / "security").mkdir(parents=True)
        frontier = {
            "selection_policy": {"stages": ["DISCOVERY", "FALSIFICATION", "REMEDIATION", "RETEST", "PORTFOLIO"]},
            "stage_contracts": {k: k.lower() for k in ["DISCOVERY", "FALSIFICATION", "REMEDIATION", "RETEST", "PORTFOLIO"]},
            "lenses": [
                {
                    "id": f"LENS-{i}",
                    "title": f"Lens {i}",
                    "purpose": "defensive purpose",
                    "customer_use": "customer use",
                    "refs": ["security/evidence.md"],
                    "safe_test": "owned fixture only",
                }
                for i in range(12)
            ],
        }
        crosswalk = {
            "frameworks": {
                "OWASP": {"name": "OWASP", "url": "https://example.invalid/owasp", "use": "risk taxonomy"},
                "NIST": {"name": "NIST", "url": "https://example.invalid/nist", "use": "risk lifecycle"},
            },
            "lens_mapping": {f"LENS-{i}": ["OWASP", "NIST"] for i in range(12)},
        }
        (root / worker.FRONTIER_PATH).write_text(json.dumps(frontier), encoding="utf-8")
        (root / worker.CROSSWALK_PATH).write_text(json.dumps(crosswalk), encoding="utf-8")
        (root / worker.PROGRAM_PATH).write_text(json.dumps({"tracks": []}), encoding="utf-8")
        (root / "security/evidence.md").write_text(
            "authorized scope observed before after retest counterevidence reproducible customer use case",
            encoding="utf-8",
        )
        return tmp, root

    def test_frontier_has_broad_rotation(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        frontier = json.loads((root / worker.FRONTIER_PATH).read_text())
        selections = [worker._select(frontier, "100", i)[0]["id"] for i in range(1, 6)]
        self.assertEqual(len(selections), len(set(selections)))

    def test_next_run_does_not_repeat_identical_five(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        frontier = json.loads((root / worker.FRONTIER_PATH).read_text())
        first = [(worker._select(frontier, "100", i)[0]["id"], worker._select(frontier, "100", i)[1]) for i in range(1, 6)]
        second = [(worker._select(frontier, "101", i)[0]["id"], worker._select(frontier, "101", i)[1]) for i in range(1, 6)]
        self.assertNotEqual(first, second)

    def test_eval_preferred_lens_is_bounded_to_two_of_ten_rounds(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        frontier = json.loads((root / worker.FRONTIER_PATH).read_text())
        selected = [worker._select(frontier, "100", i, "LENS-11")[0]["id"] for i in range(1, 11)]
        self.assertEqual(selected[0], "LENS-11")
        self.assertEqual(selected[5], "LENS-11")
        self.assertTrue(any(value != "LENS-11" for idx, value in enumerate(selected) if idx not in {0, 5}))

    def test_unknown_eval_lens_falls_back_to_broad_rotation(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        frontier = json.loads((root / worker.FRONTIER_PATH).read_text())
        normal = [worker._select(frontier, "100", i)[0]["id"] for i in range(1, 6)]
        unknown = [worker._select(frontier, "100", i, "NOT-A-LENS")[0]["id"] for i in range(1, 6)]
        self.assertEqual(normal, unknown)

    def test_round_never_self_promotes_verified(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        row = worker.run_round(root, 1, "100-1")
        self.assertEqual(row["status"], "BUILDING")
        self.assertIn("runtime_and_customer_validation_not_inferred_from_repository", row["promotion_blockers"])

    def test_assisted_round_is_explicitly_labeled_and_still_building(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        row = worker.run_round(root, 1, "100-1", "LENS-11")
        self.assertEqual(row["lens_id"], "LENS-11")
        self.assertEqual(row["selection_source"], "ai_security_eval")
        self.assertEqual(row["status"], "BUILDING")
        self.assertIn("runtime_and_customer_validation_not_inferred_from_repository", row["promotion_blockers"])

    def test_round_contains_customer_use_stage_and_safe_test(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        row = worker.run_round(root, 2, "100-2")
        self.assertTrue(row["customer_use"])
        self.assertIn(row["research_stage"], {"DISCOVERY", "FALSIFICATION", "REMEDIATION", "RETEST", "PORTFOLIO"})
        self.assertIn("owned fixture", row["safe_test_contract"])
        text = worker.render_card(row)
        self.assertIn("顧客が使う場面", text)
        self.assertIn("外部基準", text)
        self.assertIn("Promotion blocker", text)

    def test_signal_scoring_is_descriptive_not_verification(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        row = worker.run_round(root, 3, "100-3")
        hits = row["evidence"]["signals"]["signal_hits"]
        self.assertGreater(hits["authorization"], 0)
        self.assertGreater(hits["behavior"], 0)
        self.assertEqual(row["status"], "BUILDING")

    def test_every_fixture_lens_has_external_benchmark_alignment(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        for round_number in range(1, 6):
            row = worker.run_round(root, round_number, f"200-{round_number}")
            self.assertGreaterEqual(len(row["external_frameworks"]), 1)
            self.assertNotIn("external_framework_alignment_missing", row["promotion_blockers"])

    def test_missing_crosswalk_is_visible_blocker_not_verification(self):
        tmp, root = self._fixture()
        self.addCleanup(tmp.cleanup)
        (root / worker.CROSSWALK_PATH).unlink()
        row = worker.run_round(root, 1, "300")
        self.assertEqual(row["status"], "BUILDING")
        self.assertIn("external_framework_alignment_missing", row["promotion_blockers"])


if __name__ == "__main__":
    unittest.main()
