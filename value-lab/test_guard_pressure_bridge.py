import unittest

import guard_pressure_bridge as bridge


class GuardPressureBridgeTests(unittest.TestCase):
    def test_sanitize_drops_locator_like_surfaces(self):
        raw = {
            "schema": "guard-pressure-learning/v1",
            "fuzz": {"cases": 1000, "seed_count": 10, "unexpected": 0},
            "pressure_surfaces": [
                {"surface": "family:public-mutation", "cases": 100, "surprises": 0},
                {"surface": "https://example.com/private", "cases": 1, "surprises": 1},
            ],
            "research_posture": "expand-offline-boundary-diversity",
        }
        clean = bridge.sanitize(raw)
        self.assertTrue(clean["available"])
        self.assertEqual(1, len(clean["surfaces"]))
        self.assertEqual("none", clean["execution_authority"])

    def test_augment_changes_only_hypothesis(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "robustness",
            "candidate_count": 7,
            "hypothesis": "Base.",
        }
        clean = {
            "available": True,
            "cases": 10_000_000,
            "seed_count": 10,
            "unexpected": 0,
            "surfaces": [{"surface": "family:public-mutation", "cases": 100, "surprises": 0}],
            "posture": "expand-offline-boundary-diversity",
        }
        out = bridge.augment(directive, clean)
        self.assertEqual(set(directive), set(out))
        self.assertEqual(directive["focus"], out["focus"])
        self.assertIn("Guard-pressure context", out["hypothesis"])
        self.assertLessEqual(len(out["hypothesis"]), 600)

    def test_rejects_new_execution_surface(self):
        directive = {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R1",
            "focus": "robustness",
            "candidate_count": 7,
            "hypothesis": "Base.",
            "host": "example.com",
        }
        with self.assertRaises(ValueError):
            bridge.augment(directive, {"available": True})


if __name__ == "__main__":
    unittest.main()
