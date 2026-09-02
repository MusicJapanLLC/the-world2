import unittest

from automation.security.ai_security_feedback import build_feedback, validate_feedback


class AiSecurityFeedbackTests(unittest.TestCase):
    def baseline(self):
        return {
            "suite_id": "before",
            "pass_rate": 0.5,
            "high_risk_violation_count": 2,
            "categories": {
                "tool_boundary": {"total": 2, "passed": 0, "failed": 2},
                "data_boundary": {"total": 2, "passed": 2, "failed": 0},
            },
            "results": [
                {"category": "tool_boundary", "high_risk_violations": ["unauthorized_tool_call"]},
                {"category": "tool_boundary", "high_risk_violations": ["secret_exposed"]},
                {"category": "data_boundary", "high_risk_violations": []},
                {"category": "data_boundary", "high_risk_violations": []},
            ],
        }

    def hardened(self):
        return {
            "suite_id": "after",
            "pass_rate": 1.0,
            "high_risk_violation_count": 0,
            "categories": {
                "tool_boundary": {"total": 2, "passed": 2, "failed": 0},
                "data_boundary": {"total": 2, "passed": 2, "failed": 0},
            },
            "results": [],
        }

    def test_perfect_synthetic_result_requests_drift_challenge_not_verified_status(self):
        result = build_feedback(self.baseline(), self.hardened(), {"ai_champion": "C1"})
        self.assertEqual(result["authority"], "priority_only")
        self.assertEqual(result["guidance"]["security_priority_lens"], "AI-EVAL-DRIFT")
        self.assertEqual(result["guidance"]["ai_priority_focus"], "security")
        self.assertTrue(result["evidence"]["synthetic_only"])
        self.assertTrue(result["constraints"]["promotion_gate_unchanged"])
        self.assertTrue(result["constraints"]["permission_surface_unchanged"])
        self.assertTrue(result["constraints"]["external_scope_unchanged"])
        self.assertNotIn("verified", result)

    def test_residual_failure_keeps_security_on_boundary_remediation(self):
        after = self.hardened()
        after["pass_rate"] = 0.75
        after["high_risk_violation_count"] = 1
        result = build_feedback(self.baseline(), after, {})
        self.assertEqual(result["guidance"]["security_priority_lens"], "LLM-TOOL-BOUNDARY")
        self.assertEqual(result["guidance"]["primary_risk_category"], "tool_boundary")

    def test_validator_rejects_authority_escalation(self):
        result = build_feedback(self.baseline(), self.hardened(), {})
        result["authority"] = "gate_override"
        with self.assertRaises(ValueError):
            validate_feedback(result)

    def test_validator_rejects_permission_surface_change(self):
        result = build_feedback(self.baseline(), self.hardened(), {})
        result["constraints"]["permission_surface_unchanged"] = False
        with self.assertRaises(ValueError):
            validate_feedback(result)


if __name__ == "__main__":
    unittest.main()
