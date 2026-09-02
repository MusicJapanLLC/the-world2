import unittest

from automation.ai_foundry.track_progression import apply_progression, evaluate_progression


PROGRAM = {
    "tracks": [
        {"id": "AI-DEV-002", "title": "Persistent Failure and Learning Memory"},
        {"id": "AI-DEV-003", "title": "Multi-Agent Specialist League"},
    ]
}


def queue():
    return {
        "active": [
            {
                "research_id": "RND-AI-DEVELOPMENT-ACCELERATOR-001",
                "priority": 6000,
                "preferred_track_id": "AI-DEV-002",
                "current_phase": "persistent_failure_and_learning_memory",
            },
            {
                "research_id": "RND-STANDMENT-SECURITY-001",
                "priority": 5000,
                "preferred_track_id": "SEC-001",
            },
        ]
    }


def ready_summary():
    return {
        "schema": "the-world-ai-foundry-hourly/v4",
        "report_fingerprint": "runtime-proof-1",
        "failure_memory": {
            "schema": "the-world-ai-failure-memory/v1",
            "active_entries": 11,
            "recorded_failures": 9,
            "avoided_recurrences": 3,
        },
        "failure_memory_delta": {
            "recorded_failures": 4,
            "avoided_recurrences": 2,
        },
        "strategy_fixture_delta": {"regressed_cases": []},
    }


class TrackProgressionTests(unittest.TestCase):
    def test_runtime_memory_evidence_opens_specialist_lane(self):
        decision = evaluate_progression(ready_summary(), PROGRAM, queue())
        self.assertEqual(decision["decision"], "OPEN_PARALLEL_TRACK")
        self.assertEqual(decision["next_parallel_track"], "AI-DEV-003")
        self.assertTrue(decision["keep_current_track_active"])
        self.assertEqual(decision["claim_status"], "BUILDING")
        self.assertTrue(decision["gates_unchanged"])

    def test_code_or_empty_summary_never_advances(self):
        decision = evaluate_progression({}, PROGRAM, queue())
        self.assertEqual(decision["decision"], "HOLD")
        self.assertIsNone(decision["next_parallel_track"])

    def test_missing_recurrence_avoidance_holds(self):
        summary = ready_summary()
        summary["failure_memory"]["avoided_recurrences"] = 0
        summary["failure_memory_delta"]["avoided_recurrences"] = 0
        decision = evaluate_progression(summary, PROGRAM, queue())
        self.assertEqual(decision["decision"], "HOLD")
        self.assertFalse(decision["conditions"]["runtime_recurrence_avoided"])

    def test_behavioral_regression_holds(self):
        summary = ready_summary()
        summary["strategy_fixture_delta"]["regressed_cases"] = ["HOLDOUT-X"]
        decision = evaluate_progression(summary, PROGRAM, queue())
        self.assertEqual(decision["decision"], "HOLD")
        self.assertFalse(decision["conditions"]["no_behavioral_regression"])

    def test_apply_changes_only_ai_mission_priority_metadata(self):
        q = queue()
        decision = evaluate_progression(ready_summary(), PROGRAM, q)
        out = apply_progression(q, decision)
        ai = out["active"][0]
        security = out["active"][1]
        self.assertEqual(ai["preferred_track_id"], "AI-DEV-003")
        self.assertEqual(ai["previous_track_id"], "AI-DEV-002")
        self.assertTrue(ai["failure_memory_continues"])
        self.assertEqual(ai["progression_source_fingerprint"], "runtime-proof-1")
        self.assertEqual(security, q["active"][1])


if __name__ == "__main__":
    unittest.main()
