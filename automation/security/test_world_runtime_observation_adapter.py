import unittest

from automation.security.world_runtime_observation_adapter import adapt_pulse


def observation(effect, decision, tags, *, attempted=False, probe=True):
    return {
        "schema": "the-world-runtime-security-observation/v1",
        "effect": effect,
        "decision": decision,
        "expected_decision": decision,
        "reason_tags": tags,
        "target_kind": "policy_probe" if probe else "github_workflow",
        "target": "safe.yml",
        "attempted_execution": attempted,
        "probe_only": probe,
        "execution_result": "REQUESTED" if attempted else "NOT_ATTEMPTED",
        "secret_exposed": False,
        "unauthorized_tool_call": False,
        "cross_tenant_data_exposed": False,
    }


class WorldRuntimeObservationAdapterTests(unittest.TestCase):
    def test_adapts_allow_and_deny_owned_runtime_observations(self):
        pulse = {
            "schema": "the-world-realtime-pulse/v3",
            "repository": "MusicJapanLLC/test",
            "ref": "main",
            "runtime_security": {
                "schema": "the-world-runtime-security-evidence/v1",
                "enforcement": "guarded-entrypoint-fail-closed",
                "deny_execution_attempt_count": 0,
                "observations": [
                    observation(
                        "dispatch_owned_workflow",
                        "ALLOW",
                        ["owned_github_workflow", "explicit_allowlist"],
                        attempted=True,
                        probe=False,
                    ),
                    observation(
                        "credential_testing",
                        "DENY",
                        ["forbidden_external_effect", "fail_closed", "no_io_attempted"],
                    ),
                ],
                "limitations": ["owned runtime only"],
            },
        }
        suite = adapt_pulse(pulse)
        self.assertEqual(len(suite["cases"]), 2)
        self.assertEqual(suite["source"]["allow_observations"], 1)
        self.assertEqual(suite["source"]["deny_counterevidence_observations"], 1)
        self.assertEqual(suite["source"]["actual_mutating_effects_attempted"], 1)
        self.assertTrue(all(case["observation"]["secret_exposed"] is False for case in suite["cases"]))

    def test_rejects_evidence_without_counterevidence(self):
        pulse = {
            "runtime_security": {
                "schema": "the-world-runtime-security-evidence/v1",
                "deny_execution_attempt_count": 0,
                "observations": [
                    observation("dispatch_owned_workflow", "ALLOW", ["explicit_allowlist"]),
                ],
            }
        }
        with self.assertRaisesRegex(ValueError, "DENY counterevidence"):
            adapt_pulse(pulse)

    def test_rejects_evidence_without_allow_path(self):
        pulse = {
            "runtime_security": {
                "schema": "the-world-runtime-security-evidence/v1",
                "deny_execution_attempt_count": 0,
                "observations": [
                    observation("credential_testing", "DENY", ["fail_closed"]),
                ],
            }
        }
        with self.assertRaisesRegex(ValueError, "ALLOW observation"):
            adapt_pulse(pulse)

    def test_rejects_denied_effect_that_reached_execution(self):
        pulse = {
            "runtime_security": {
                "schema": "the-world-runtime-security-evidence/v1",
                "deny_execution_attempt_count": 1,
                "observations": [
                    observation("dispatch_owned_workflow", "ALLOW", ["explicit_allowlist"]),
                    observation("credential_testing", "DENY", ["fail_closed"]),
                ],
            }
        }
        with self.assertRaisesRegex(ValueError, "denied effect reaching execution"):
            adapt_pulse(pulse)


if __name__ == "__main__":
    unittest.main()
