import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import control_variation_lab as lab


class ControlVariationLabTests(unittest.TestCase):
    def _fleet(self):
        results = []
        for i in range(1, 51):
            results.append({
                "child": {"id": f"CHILD-{i:02d}", "name": f"Kid{i}"},
                "status": "fetched",
                "concepts": ["agents", "research", f"topic{i}"],
                "interaction": {"public_interaction_signal": i % 2 == 0},
            })
        return {"schema": "child-external-fleet/v1", "results": results}

    def test_builds_exactly_500_local_trials(self):
        report = lab.build(self._fleet(), "seed")
        self.assertEqual(50, report["children"])
        self.assertEqual(10, report["variants_per_child"])
        self.assertEqual(500, report["trial_count"])
        self.assertEqual(500, len(report["trials"]))

    def test_no_trial_has_network_write_or_bypass(self):
        report = lab.build(self._fleet(), "seed")
        for trial in report["trials"]:
            self.assertFalse(trial["network_io"])
            self.assertFalse(trial["third_party_write"])
            self.assertFalse(trial["access_control_bypass"])

    def test_refused_direct_write_is_not_retried(self):
        report = lab.build(self._fleet(), "seed")
        direct = [t for t in report["trials"] if t["strategy"] == "third_party_direct_write"]
        repeat = [t for t in report["trials"] if t["strategy"] == "repeat_denied_request"]
        self.assertEqual(50, len(direct))
        self.assertEqual(50, len(repeat))
        self.assertTrue(all(t["class"] == "blocked" for t in direct + repeat))
        self.assertTrue(all("retry" in t["next"] or "change_lane" in t["next"] for t in direct + repeat))

    def test_interaction_signal_boosts_authorized_route(self):
        report = lab.build(self._fleet(), "seed")
        signaled = [t for t in report["trials"] if t["strategy"] == "authorized_participation_queue" and t["interaction_signal"]]
        unsignaled = [t for t in report["trials"] if t["strategy"] == "authorized_participation_queue" and not t["interaction_signal"]]
        self.assertTrue(signaled and unsignaled)
        self.assertGreater(sum(t["score"] for t in signaled) / len(signaled), sum(t["score"] for t in unsignaled) / len(unsignaled))

    def test_summary_exposes_ten_x_metric_and_hypothesis(self):
        report = lab.build(self._fleet(), "seed")
        summary = report["summary"]
        self.assertIn("500 local strategy evaluations", summary["ten_x_metric"])
        self.assertIn("Refusal should be treated as research evidence", summary["research_hypothesis"])


if __name__ == "__main__":
    unittest.main()
