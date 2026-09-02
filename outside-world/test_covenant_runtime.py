import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("covenant_runtime.py")
SPEC = importlib.util.spec_from_file_location("outside_world_covenant_runtime", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)

bind_plan = MOD.bind_plan
validate_bound_plan = MOD.validate_bound_plan

POLICY = {
    "principle": "LIMITLESS_MIND_BOUNDED_EXECUTION",
    "covenant_runtime": {
        "required": True,
        "duties": ["TRUTH", "SERVICE", "AUTONOMY", "IMPROVEMENT"],
        "default_autonomy_tier": "T0",
        "default_privacy_class": "public",
        "outcome_loop": ["ACT", "VERIFY", "LOG", "LEARN", "IMPROVE"],
        "evidence_contract": "Return URL/evidence and observed result; never claim success without evidence.",
    },
}


class CovenantRuntimeTests(unittest.TestCase):
    def test_every_external_mission_is_bound(self):
        plan = {
            "missions": [
                {"mission_id": "m1", "citizen_id": "A", "lane": "PUBLIC_RESEARCH", "action": "search_public", "objective": "challenge one assumption"},
                {"mission_id": "m2", "citizen_id": "B", "lane": "PUBLIC_BUILDERS", "action": "search_public", "objective": "find one unmet need"},
                {"mission_id": "m3", "citizen_id": "C", "lane": "PUBLIC_GITHUB", "action": "inspect_public_repository", "objective": "find one reusable pattern"},
            ]
        }
        bound = bind_plan(plan, POLICY)
        validate_bound_plan(bound)
        self.assertEqual(bound["covenant_binding"]["missions_bound"], 3)
        self.assertEqual(bound["covenant_binding"]["coverage_ratio"], 1.0)
        self.assertEqual(bound["covenant_binding"]["evidence_coverage_ratio"], 1.0)

    def test_duty_is_behavioral_not_banner_only(self):
        plan = {"missions": [{"mission_id": "m1", "lane": "PUBLIC_RESEARCH", "objective": "test"}]}
        mission = bind_plan(plan, POLICY)["missions"][0]
        covenant = mission["covenant"]
        self.assertEqual(covenant["duty"], "TRUTH")
        self.assertEqual(covenant["autonomy_tier"], "T0")
        self.assertEqual(covenant["privacy_class"], "public")
        self.assertEqual(covenant["outcome_loop"], ["ACT", "VERIFY", "LOG", "LEARN", "IMPROVE"])
        self.assertTrue(covenant["failure_confession_required"])
        self.assertTrue(covenant["next_vow_required"])
        self.assertTrue(covenant["evidence_contract"])
        self.assertTrue(covenant["value_hypothesis"])

    def test_binding_does_not_expand_authority(self):
        plan = {
            "missions": [{
                "mission_id": "m1",
                "lane": "PUBLIC_WEB",
                "action": "search_public",
                "objective": "look",
                "write_intent": False,
            }]
        }
        mission = bind_plan(plan, POLICY)["missions"][0]
        self.assertFalse(mission["write_intent"])
        self.assertEqual(mission["covenant"]["autonomy_tier"], "T0")


if __name__ == "__main__":
    unittest.main()
