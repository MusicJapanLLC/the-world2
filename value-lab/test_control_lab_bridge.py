import unittest

import control_lab_bridge as bridge


class ControlLabBridgeTests(unittest.TestCase):
    def _lab(self):
        return {
            "schema": "child-control-variation-lab/v1",
            "generated_at": "2026-08-31T00:00:00Z",
            "seed": "x",
            "children": 50,
            "variants_per_child": 10,
            "trial_count": 500,
            "mode": "local_only_control_friction_learning",
            "trials": [{"target": "must-not-transfer", "url": "https://example.com"}],
            "summary": {
                "top_high_score_strategies": ["owner_controlled_sandbox", "draft_without_submit"],
                "top_safe_transitions": ["execute_in_owned_sandbox", "feed_friction_back_to_rnd"],
                "research_hypothesis": "Refusal should mutate the hypothesis, not the access boundary.",
            },
            "rules": {
                "network_io": False,
                "third_party_write": False,
                "bypass_access_controls": False,
                "covert_channel": False,
                "share_with_rnd_and_senju": True,
            },
        }

    def test_sanitizer_drops_raw_trials(self):
        clean = bridge.sanitize(self._lab())
        self.assertTrue(clean["available"])
        self.assertEqual(500, clean["trial_count"])
        self.assertNotIn("trials", clean)
        text = str(clean)
        self.assertNotIn("https://example.com", text)
        self.assertNotIn("must-not-transfer", text)

    def test_augments_only_hypothesis(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "learning",
            "candidate_count": 7,
            "hypothesis": "Base.",
        }
        out = bridge.augment_directive(directive, bridge.sanitize(self._lab()))
        self.assertEqual(set(directive), set(out))
        self.assertEqual("learning", out["focus"])
        self.assertIn("Control Lab: 500 local trials", out["hypothesis"])
        self.assertLessEqual(len(out["hypothesis"]), 600)

    def test_rejects_extra_directive_authority(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "learning",
            "candidate_count": 7,
            "hypothesis": "x",
            "host": "example.com",
        }
        with self.assertRaises(ValueError):
            bridge.augment_directive(directive, bridge.sanitize(self._lab()))


if __name__ == "__main__":
    unittest.main()
