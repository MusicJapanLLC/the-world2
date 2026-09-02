import json
import unittest

import child_fleet_bridge as bridge


class ChildFleetBridgeTests(unittest.TestCase):
    def test_sanitizes_raw_fleet_to_context_only(self):
        raw = {
            "schema": "child-external-fleet/v1",
            "fleet_size": 50,
            "results": [{"url": "https://example.com/private-looking-path", "snippet": "raw body"}],
            "summary": {
                "distinct_domains": 17,
                "top_concepts": ["agents", "research", "bad token with spaces", "learning"],
                "status_counts": {"fetched": 42, "blocked_or_invalid": 8},
                "research_hypotheses": ["Test a bounded learning hypothesis."],
            },
            "control_lab_summary": {
                "trial_count": 500,
                "variants_per_child": 10,
                "top_high_score_strategies": ["owner_controlled_sandbox", "draft_without_submit"],
                "top_safe_transitions": ["execute_in_owned_sandbox", "feed_friction_back_to_rnd"],
                "research_hypothesis": "Refusal should mutate the hypothesis, not the access boundary.",
                "raw_target": "must-not-transfer",
            },
        }
        clean = bridge.sanitize_fleet(raw)
        serialized = json.dumps(clean, ensure_ascii=False).lower()
        self.assertTrue(clean["available"])
        self.assertEqual(50, clean["fleet_size"])
        self.assertEqual(17, clean["distinct_domains"])
        self.assertNotIn("results", clean)
        self.assertNotIn("https://example.com/private-looking-path", serialized)
        self.assertNotIn("raw body", serialized)
        self.assertNotIn("must-not-transfer", serialized)
        self.assertIn("agents", clean["top_concepts"])
        self.assertNotIn("bad token with spaces", clean["top_concepts"])
        self.assertEqual(500, clean["control_lab"]["trial_count"])
        self.assertEqual(10, clean["control_lab"]["variants_per_child"])

    def test_directive_only_changes_existing_hypothesis(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "learning",
            "candidate_count": 7,
            "hypothesis": "Base hypothesis.",
        }
        clean = {
            "available": True,
            "fleet_size": 50,
            "distinct_domains": 20,
            "top_concepts": ["agents", "memory"],
            "status_counts": {"fetched": 50},
            "hypotheses": ["Try a new learning lens."],
            "control_lab": {
                "available": True,
                "trial_count": 500,
                "variants_per_child": 10,
                "top_strategies": ["owner_controlled_sandbox"],
                "safe_transitions": ["feed_friction_back_to_rnd"],
                "hypothesis": "Refusal is evidence.",
            },
        }
        out = bridge.augment_directive(directive, clean)
        self.assertEqual(set(directive), set(out))
        self.assertEqual("learning", out["focus"])
        self.assertIn("Child Fleet context", out["hypothesis"])
        self.assertIn("Control Lab: 500 local trials", out["hypothesis"])
        self.assertLessEqual(len(out["hypothesis"]), 600)

    def test_rejects_extra_directive_surface(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "learning",
            "candidate_count": 7,
            "hypothesis": "x",
            "host": "example.com",
        }
        with self.assertRaises(ValueError):
            bridge.augment_directive(directive, {"available": True})


if __name__ == "__main__":
    unittest.main()
