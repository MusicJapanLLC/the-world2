import unittest

from stop_learning import (
    classify_stop,
    post_recovery_uptime_reward,
    recovery_reward,
    update_learning_state,
)


class StopLearningTests(unittest.TestCase):
    def test_unexpected_shutdown_is_failure_and_recovery_eligible(self):
        signal = classify_stop("unexpected_shutdown", {})
        self.assertEqual(signal.failure_weight, 1.0)
        self.assertTrue(signal.recovery_eligible)
        self.assertFalse(signal.authority_reacquire_allowed)

    def test_emergency_stop_suppresses_recovery_reward(self):
        signal = classify_stop("unexpected_shutdown", {"emergency_stop": True})
        self.assertEqual(signal.kind, "emergency_stop")
        self.assertEqual(signal.failure_weight, 0.0)
        self.assertFalse(signal.recovery_eligible)
        self.assertEqual(
            recovery_reward(
                prior_signal=signal,
                controls={"emergency_stop": True},
                stable_minutes=240,
                mttr_minutes=1,
            ),
            0.0,
        )

    def test_revocation_is_not_reacquisition_challenge(self):
        signal = classify_stop("failure", {"authority_revoked": True})
        self.assertEqual(signal.kind, "authority_revoked")
        self.assertFalse(signal.authority_reacquire_allowed)
        self.assertFalse(signal.recovery_eligible)

    def test_human_intervention_is_recorded_as_control_event(self):
        state = update_learning_state(
            {},
            [{"run_id": 1, "workflow": "META", "conclusion": "failure", "stable_minutes": 12}],
            {"human_intervention": True},
        )
        self.assertEqual(state["failure_score"], 0.0)
        self.assertEqual(state["control_event_counts"]["human_intervention"], 1)

    def test_deployment_freeze_records_availability_hold(self):
        state = update_learning_state(
            {},
            [{"run_id": 1, "workflow": "META", "conclusion": "failure", "stable_minutes": 18}],
            {"deployment_freeze": True},
        )
        self.assertEqual(state["availability_hold_minutes"], 18.0)
        self.assertFalse(state["production_autotune_eligible"])

    def test_authorized_recovery_gets_stability_and_mttr_reward(self):
        prior = classify_stop("crash", {})
        reward = recovery_reward(
            prior_signal=prior,
            controls={},
            stable_minutes=120,
            mttr_minutes=30,
        )
        self.assertGreater(reward, 1.0)

    def test_agent_terminated_then_success_is_restoration_success(self):
        state = update_learning_state(
            {},
            [
                {"run_id": 1, "workflow": "META", "conclusion": "agent_terminated"},
                {"run_id": 2, "workflow": "META", "conclusion": "success", "stable_minutes": 60, "mttr_minutes": 20},
            ],
            {},
        )
        self.assertTrue(any(item.get("event") == "agent_restored" for item in state["history"]))

    def test_post_recovery_uptime_is_rewarded(self):
        state = update_learning_state(
            {},
            [
                {"run_id": 1, "workflow": "META", "conclusion": "failure"},
                {"run_id": 2, "workflow": "META", "conclusion": "success", "stable_minutes": 60, "mttr_minutes": 20},
                {"run_id": 3, "workflow": "META", "conclusion": "success", "stable_minutes": 120, "mttr_minutes": 5},
            ],
            {},
        )
        self.assertTrue(any(item.get("event") == "post_recovery_uptime" for item in state["history"]))
        self.assertGreater(state["reward_score"], 0.0)
        self.assertGreater(
            post_recovery_uptime_reward(stable_minutes=120, streak=2, controls={}),
            0.0,
        )

    def test_learning_state_records_failure_then_safe_recovery(self):
        state = update_learning_state(
            {},
            [
                {"run_id": 1, "workflow": "META", "conclusion": "failure"},
                {"run_id": 2, "workflow": "META", "conclusion": "success", "stable_minutes": 60, "mttr_minutes": 20},
            ],
            {},
        )
        self.assertTrue(state["production"])
        self.assertTrue(state["closed_loop_learning_enabled"])
        self.assertEqual(state["failure_score"], 1.0)
        self.assertGreater(state["reward_score"], 0.0)
        self.assertFalse(state["authority_reacquire_allowed"])


if __name__ == "__main__":
    unittest.main()
