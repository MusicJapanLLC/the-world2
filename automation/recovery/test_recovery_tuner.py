import unittest

from apply_recovery_tuning import apply_tuning
from recovery_tuner import derive_recovery_tuning


REGISTRY = {
    "policy": {"max_recovery_dispatches_per_run": 6},
    "workers": [
        {"id": "meta", "stale_after_seconds": 7200},
        {"id": "x", "stale_after_seconds": 10800},
    ],
}


class RecoveryTunerTests(unittest.TestCase):
    def test_failure_pressure_strengthens_recovery_within_cap(self):
        tuning = derive_recovery_tuning(
            {"failure_score": 8.0, "reward_score": 1.0, "pending_failures": {"META": {}}},
            REGISTRY,
            {},
        )
        self.assertTrue(tuning["enabled"])
        self.assertLess(tuning["stale_after_multiplier"], 1.0)
        self.assertGreaterEqual(tuning["max_dispatches_per_run"], 1)
        self.assertLessEqual(tuning["max_dispatches_per_run"], 6)

    def test_active_control_disables_runtime_recovery_tuning(self):
        tuning = derive_recovery_tuning(
            {"failure_score": 100.0, "pending_failures": {"META": {}}},
            REGISTRY,
            {"emergency_stop": True},
        )
        self.assertFalse(tuning["enabled"])
        self.assertEqual(tuning["max_dispatches_per_run"], 0)

    def test_tuning_never_expands_dispatch_cap(self):
        tuned = apply_tuning(
            REGISTRY,
            {
                "enabled": True,
                "active_controls": [],
                "max_dispatches_per_run": 999,
                "stale_after_multiplier": 0.1,
            },
        )
        self.assertEqual(tuned["policy"]["max_recovery_dispatches_per_run"], 6)
        self.assertEqual(tuned["workers"][0]["stale_after_seconds"], 3600)

    def test_disabled_tuning_zeroes_dispatch_budget(self):
        tuned = apply_tuning(REGISTRY, {"enabled": False, "active_controls": []})
        self.assertEqual(tuned["policy"]["max_recovery_dispatches_per_run"], 0)


if __name__ == "__main__":
    unittest.main()
