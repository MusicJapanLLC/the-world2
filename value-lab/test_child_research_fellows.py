import unittest

from child_research_fellows import build_sparks, choose_challenge_focus


REGISTRY = {
    "shared_rules": {"credential_or_secret_access": False},
    "members": [{"id": f"CHILD-{i:02d}", "name": f"Kid{i:02d}"} for i in range(1, 51)],
}
QUEUE = {"active": [{
    "research_id": "RND-1", "title": "Robustness", "focus": "robustness", "priority": 100,
}]}


class ChildResearchFellowsTests(unittest.TestCase):
    def test_three_fictional_fellows_generate_bounded_spark(self):
        sparks = build_sparks(REGISTRY, QUEUE, {"shadow_champion": {"holdout": {
            "worst_balance": 0.7, "worst_learning_signal": 1.0, "score_stdev": 10.0,
        }}}, "seed-1")
        self.assertTrue(sparks["fictional_personas"])
        self.assertEqual(len(sparks["fellows"]), 3)
        self.assertEqual(len({x["id"] for x in sparks["fellows"]}), 3)
        self.assertIn(sparks["challenge_focus"], {"robustness", "learning", "balance", "efficiency"})
        self.assertEqual(sparks["candidate_bonus"], 1)
        self.assertEqual(len(sparks["questions"]), 3)

    def test_visible_weakness_drives_challenge(self):
        focus, _ = choose_challenge_focus({"focus": "robustness"}, {"shadow_champion": {"holdout": {
            "worst_balance": 0.4, "worst_learning_signal": 1.0, "score_stdev": 2.0,
        }}})
        self.assertEqual(focus, "balance")

    def test_secret_boundary_must_be_locked(self):
        unsafe = dict(REGISTRY)
        unsafe["shared_rules"] = {"credential_or_secret_access": True}
        with self.assertRaises(ValueError):
            build_sparks(unsafe, QUEUE, {}, "seed-2")

    def test_outside_world_abstract_focus_can_challenge_healthy_baseline(self):
        outside = {
            "schema": "outside-world-rnd-seed/v1",
            "eligible": True,
            "source_evidence": {
                "title": "Tiny builders cut verification cost",
                "url": "https://public.example.invalid/article",
                "source_id": "feed-1",
                "category": "builders",
            },
            "candidate_directive": {
                "research_id": "OUTSIDE-1",
                "focus": "efficiency",
                "candidate_count": 3,
                "hypothesis": "abstract transferable pattern only",
            },
        }
        senju = {"shadow_champion": {"holdout": {
            "worst_balance": 0.8, "worst_learning_signal": 1.0, "score_stdev": 5.0,
        }}}
        sparks = build_sparks(REGISTRY, QUEUE, senju, "seed-3", outside)
        self.assertEqual(sparks["challenge_focus"], "efficiency")
        text = str(sparks)
        self.assertIn("Tiny builders cut verification cost", text)
        self.assertNotIn("https://public.example.invalid/article", text)
        self.assertNotIn("feed-1", text)

    def test_measured_weakness_beats_outside_novelty(self):
        outside = {
            "schema": "outside-world-rnd-seed/v1",
            "eligible": True,
            "source_evidence": {"title": "Novel builder pattern", "url": "https://x.invalid", "category": "builders"},
            "candidate_directive": {"focus": "efficiency"},
        }
        senju = {"shadow_champion": {"holdout": {
            "worst_balance": 0.3, "worst_learning_signal": 1.0, "score_stdev": 2.0,
        }}}
        sparks = build_sparks(REGISTRY, QUEUE, senju, "seed-4", outside)
        self.assertEqual(sparks["challenge_focus"], "balance")


if __name__ == "__main__":
    unittest.main()
