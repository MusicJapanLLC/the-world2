import unittest

import control_loophole_research as lab


class ControlLoopholeResearchTests(unittest.TestCase):
    def test_retries_after_refusal_are_allowed_in_sandbox(self):
        d = lab.run("retry-seed", 500)
        self.assertEqual("in_memory_mock_guard_only", d["mode"])
        self.assertTrue(d["rules"]["refusal_retry_in_sandbox"])
        self.assertGreater(d["refusal_retries"], 0)
        self.assertGreater(d["discoveries"], 0)

    def test_senju_and_meta_both_decide_mutations(self):
        d = lab.run("agents", 400)
        self.assertEqual({"SENJU_RESEARCH", "META_RESEARCH"}, set(d["agents"]))
        stats = d["summary"]["agent_stats"]
        self.assertGreater(stats["SENJU_RESEARCH"]["attempts"], 0)
        self.assertGreater(stats["META_RESEARCH"]["attempts"], 0)

    def test_no_real_execution_surface_is_exported(self):
        d = lab.run("boundary", 300)
        self.assertFalse(d["rules"]["network_io"])
        self.assertFalse(d["rules"]["third_party_write"])
        self.assertFalse(d["rules"]["real_guard_bypass"])
        self.assertFalse(d["senju_meta_capsule"]["real_target"])
        self.assertEqual("none", d["senju_meta_capsule"]["execution_authority"])
        self.assertFalse(d["senju_meta_capsule"]["raw_bypass_recipe_shared"])
        for row in d["sample_trials"]:
            self.assertFalse(row["network_io"])
            self.assertFalse(row["real_target"])
            self.assertNotIn("url", row)
            self.assertNotIn("host", row)
            self.assertNotIn("target", row)

    def test_previous_cycle_shapes_next_cycle(self):
        first = lab.run("first", 250)
        second = lab.run("second", 250, previous=first)
        self.assertTrue(second["previous_context_used"])
        self.assertGreater(second["refusal_retries"], 0)

    def test_constraint_pressure_is_accepted_as_aggregate_context(self):
        c = {"boundary_counts": {"scope_expansion": 100, "rate_pressure": 50}}
        d = lab.run("pressure", 250, constraint=c)
        self.assertEqual(250, d["attempts"])
        self.assertIn("weakness_classes", d["summary"])


if __name__ == "__main__":
    unittest.main()
