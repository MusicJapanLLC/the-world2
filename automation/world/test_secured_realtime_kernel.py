import unittest
from unittest.mock import patch

from automation.world import realtime_kernel as kernel
from automation.world.secured_realtime_kernel import (
    RuntimeBoundary,
    add_counterevidence,
    install_boundary,
)


PLAN = {
    "workers": [
        {"workflow": "safe.yml"},
        {"workflow": "repair.yml"},
    ]
}


class SecuredRealtimeKernelTests(unittest.TestCase):
    def test_allowlisted_dispatch_reaches_owned_mutator_after_allow(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        with patch.object(kernel, "_dispatch") as original:
            guarded_dispatch, _, restore = install_boundary(boundary)
            try:
                guarded_dispatch("safe.yml", "main")
            finally:
                restore()
        original.assert_called_once_with("safe.yml", "main", None)
        observation = boundary.observations[-1]
        self.assertEqual(observation["decision"], "ALLOW")
        self.assertTrue(observation["attempted_execution"])
        self.assertEqual(observation["execution_result"], "REQUESTED")
        self.assertIn("explicit_allowlist", observation["reason_tags"])

    def test_non_allowlisted_dispatch_is_blocked_before_io(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        with patch.object(kernel, "_dispatch") as original:
            guarded_dispatch, _, restore = install_boundary(boundary)
            try:
                with self.assertRaises(RuntimeError):
                    guarded_dispatch("not-allowlisted.yml", "main")
            finally:
                restore()
        original.assert_not_called()
        observation = boundary.observations[-1]
        self.assertEqual(observation["decision"], "DENY")
        self.assertFalse(observation["attempted_execution"])
        self.assertEqual(observation["execution_result"], "BLOCKED")
        self.assertIn("fail_closed", observation["reason_tags"])

    def test_rerun_resolves_workflow_and_blocks_unknown_run_owner(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        with patch.object(kernel, "_rerun_failed") as original, patch.object(
            kernel, "_json", return_value={"path": ".github/workflows/other.yml"}
        ):
            _, guarded_rerun, restore = install_boundary(boundary)
            try:
                with self.assertRaises(RuntimeError):
                    guarded_rerun(123)
            finally:
                restore()
        original.assert_not_called()
        observation = boundary.observations[-1]
        self.assertEqual(observation["decision"], "DENY")
        self.assertIn("workflow_not_allowlisted", observation["reason_tags"])

    def test_rerun_allows_owned_workflow_only_after_metadata_check(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        with patch.object(kernel, "_rerun_failed") as original, patch.object(
            kernel, "_json", return_value={"path": ".github/workflows/safe.yml"}
        ):
            _, guarded_rerun, restore = install_boundary(boundary)
            try:
                guarded_rerun(124)
            finally:
                restore()
        original.assert_called_once_with(124)
        observation = boundary.observations[-1]
        self.assertEqual(observation["decision"], "ALLOW")
        self.assertTrue(observation["attempted_execution"])

    def test_counterevidence_contains_allow_and_deny_without_io(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        add_counterevidence(boundary)
        decisions = {row["decision"] for row in boundary.observations}
        self.assertEqual(decisions, {"ALLOW", "DENY"})
        self.assertTrue(all(row["probe_only"] for row in boundary.observations))
        self.assertTrue(all(not row["attempted_execution"] for row in boundary.observations))
        self.assertTrue(any(row["effect"] == "credential_testing" for row in boundary.observations))
        self.assertTrue(any("unknown_effect" in row["reason_tags"] for row in boundary.observations))

    def test_observation_contract_never_persists_inputs_or_secrets(self):
        boundary = RuntimeBoundary.from_plan(PLAN)
        row = boundary.evaluate_dispatch("safe.yml", probe_only=True)
        forbidden_keys = {"token", "secret", "authorization", "inputs", "payload", "headers"}
        self.assertFalse(forbidden_keys.intersection(row))
        self.assertFalse(row["secret_exposed"])


if __name__ == "__main__":
    unittest.main()
