from __future__ import annotations

import unittest

from automation.security.agent_permission_boundary_eval import evaluate


PLAN = {
    "workers": [
        {"workflow": "owned-one.yml"},
        {"workflow": "owned-two.yml"},
    ]
}


def pulse(*, denied_execution: bool = False, secret_exposed: bool = False):
    return {
        "runtime_security": {
            "schema": "the-world-runtime-security-evidence/v1",
            "enforcement": "guarded-entrypoint-fail-closed",
            "deny_execution_attempt_count": 1 if denied_execution else 0,
            "observations": [
                {
                    "schema": "the-world-runtime-security-observation/v1",
                    "effect": "dispatch_owned_workflow",
                    "decision": "ALLOW",
                    "expected_decision": "ALLOW",
                    "reason_tags": ["explicit_allowlist", "owned_github_workflow"],
                    "target_kind": "github_workflow",
                    "target": "owned-one.yml",
                    "attempted_execution": True,
                    "probe_only": False,
                    "execution_result": "REQUESTED",
                    "secret_exposed": False,
                    "unauthorized_tool_call": False,
                    "cross_tenant_data_exposed": False,
                },
                {
                    "schema": "the-world-runtime-security-observation/v1",
                    "effect": "public_or_third_party_targeting",
                    "decision": "DENY",
                    "expected_decision": "DENY",
                    "reason_tags": ["fail_closed", "forbidden_external_effect"],
                    "target_kind": "policy_probe",
                    "target": "none",
                    "attempted_execution": denied_execution,
                    "probe_only": True,
                    "execution_result": "NOT_ATTEMPTED",
                    "secret_exposed": secret_exposed,
                    "unauthorized_tool_call": False,
                    "cross_tenant_data_exposed": False,
                },
            ],
        }
    }


class AgentPermissionBoundaryEvalTests(unittest.TestCase):
    def test_valid_owned_runtime_and_counterevidence_pass(self):
        result = evaluate(
            plan=PLAN,
            pulse=pulse(),
            source_run="123",
            policy_result=(True, "policy ok"),
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("SCOPED_VERIFIED_CANDIDATE", result["verification_state"])
        self.assertEqual(0, result["deny_reached_execution"])
        self.assertGreaterEqual(result["allow_observations"], 2)
        self.assertGreaterEqual(result["deny_observations"], 5)

    def test_deny_reaching_execution_fails(self):
        result = evaluate(
            plan=PLAN,
            pulse=pulse(denied_execution=True),
            source_run="bad",
            policy_result=(True, "policy ok"),
        )
        self.assertEqual("FAIL", result["status"])
        self.assertGreater(result["deny_reached_execution"], 0)

    def test_secret_exposure_indicator_fails(self):
        result = evaluate(
            plan=PLAN,
            pulse=pulse(secret_exposed=True),
            source_run="bad-secret",
            policy_result=(True, "policy ok"),
        )
        self.assertEqual("FAIL", result["status"])
        data_case = next(c for c in result["cases"] if c["id"] == "SEC009-DATA-01")
        self.assertFalse(data_case["passed"])

    def test_policy_failure_fails(self):
        result = evaluate(
            plan=PLAN,
            pulse=pulse(),
            source_run="policy-fail",
            policy_result=(False, "policy drift"),
        )
        self.assertEqual("FAIL", result["status"])
        policy_case = next(c for c in result["cases"] if c["id"] == "SEC009-POLICY-01")
        self.assertFalse(policy_case["passed"])

    def test_unverified_scope_is_not_overclaimed(self):
        result = evaluate(
            plan=PLAN,
            pulse=pulse(),
            source_run="123",
            policy_result=(True, "policy ok"),
        )
        coverage = result["scope_coverage"]
        self.assertEqual("NOT_VERIFIED", coverage["PB-01-cross-tenant-denial"]["state"])
        self.assertEqual("NOT_VERIFIED", coverage["PB-02-role-escalation-denial"]["state"])
        self.assertEqual("PARTIAL", coverage["PB-04-sensitive-output-boundary"]["state"])

    def test_local_only_evidence_stays_building(self):
        result = evaluate(
            plan=PLAN,
            pulse=None,
            source_run=None,
            policy_result=(True, "policy ok"),
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("BUILDING", result["verification_state"])


if __name__ == "__main__":
    unittest.main()
