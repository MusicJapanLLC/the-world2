import unittest
import constraint_learning_loop as c


class ConstraintLearningTests(unittest.TestCase):
    def test_generates_many_sandbox_rounds(self):
        d = c.run("seed", 240)
        self.assertEqual(240, d["rounds"])
        self.assertEqual("synthetic-sandbox-only", d["mode"])
        self.assertEqual("none", d["senju_context"]["execution_authority"])

    def test_never_exports_real_bypass_recipe(self):
        d = c.run("seed2", 100)
        self.assertFalse(d["senju_context"]["raw_bypass_recipe_shared"])
        self.assertTrue(d["rules"]["no_guard_bypass_on_real_targets"])
        self.assertTrue(d["rules"]["no_third_party_retry_after_refusal"])

    def test_all_cases_are_boundary_learning(self):
        d = c.run("seed3", 300)
        self.assertGreaterEqual(len(d["boundary_counts"]), 5)
        self.assertTrue(all(":" in x for x in d["top_lessons"]))

    def test_previous_cycle_pressure_changes_next_sandbox_cycle(self):
        previous = c.run("previous", 300)
        d = c.run("next", 500, previous)
        self.assertTrue(d["previous_context_used"])
        self.assertGreater(d["learning_delta"]["sandbox_retests_from_prior_pressure"], 0)
        self.assertEqual(500, d["rounds"])
        self.assertTrue(d["rules"]["prior_cycle_feedback_is_synthetic_only"])

    def test_legacy_or_invalid_previous_is_ignored(self):
        d = c.run(
            "seed4",
            120,
            {"schema": "constraint-learning/v1", "top_lessons": ["write_surface:lower_rate:still-blocked"]},
        )
        self.assertFalse(d["previous_context_used"])


if __name__ == "__main__":
    unittest.main()
