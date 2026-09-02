import json
import tempfile
import unittest
from pathlib import Path

from automation.world import ai_security_joint_lab as joint


class JointLabTests(unittest.TestCase):
    def test_combines_ai_security_and_research_without_verification(self):
        packet = joint.build_packet(
            {"report_fingerprint": "ai-1", "weakest_next_focus": "reliability", "material_delta": True, "rounds": 120},
            {"run_id": "sec-1", "priority_next": {"lens_id": "RECOVERY", "stage": "RETEST", "artifact": "Recovery Pack", "next_improvement": "rerun"}},
            {"github_run_id": 9, "program_count": 2, "trial_count": 900, "cycles": [{"program_key": "RESILIENCE", "mode": "REPLICATE", "novelty": 0.4, "confidence": 0.7, "reproducibility": 0.9}]},
        )
        self.assertEqual(packet["status"], "BUILDING")
        self.assertEqual(packet["joint_focus"]["research_bias"], "RESILIENCE")
        self.assertIn("RECOVERY", packet["joint_question"])
        self.assertTrue(packet["promotion_blockers"])
        self.assertEqual(packet["owner_action"], "NONE")

        handoff = packet["handoff"]
        self.assertEqual(handoff["schema"], "the-world-ai-security-handoff/v1")
        self.assertEqual(handoff["authority"], "priority_only")
        self.assertEqual(handoff["handoff_token"], packet["assist_seed_short"])
        self.assertEqual(handoff["guidance"]["ai_priority_focus"], "reliability")
        self.assertEqual(handoff["guidance"]["security_priority_lens"], "RECOVERY")
        self.assertEqual(handoff["guidance"]["security_priority_stage"], "RETEST")
        self.assertEqual(handoff["guidance"]["research_bias"], "RESILIENCE")
        self.assertEqual(handoff["freshness"]["max_consumer_cycles"], 2)
        self.assertTrue(handoff["constraints"]["promotion_gate_unchanged"])
        self.assertTrue(handoff["constraints"]["permission_surface_unchanged"])
        self.assertTrue(handoff["constraints"]["external_scope_unchanged"])
        self.assertTrue(handoff["constraints"]["verification_authority_unchanged"])
        self.assertTrue(handoff["constraints"]["external_target_expansion_forbidden"])

    def test_missing_sources_fail_soft_and_are_deterministic(self):
        a = joint.build_packet({}, {}, {})
        b = joint.build_packet({}, {}, {})
        self.assertEqual(a["assist_seed"], b["assist_seed"])
        self.assertEqual(a["joint_focus"]["security_lens"], "UNKNOWN")
        self.assertEqual(a["status"], "BUILDING")
        self.assertEqual(a["handoff"]["guidance"]["ai_priority_focus"], "security")
        self.assertEqual(a["handoff"]["freshness"]["stale_behavior"], "ignore_and_fall_back_to_local_evidence")

    def test_security_boundary_biases_governance(self):
        packet = joint.build_packet(
            {"weakest_next_focus": "architecture"},
            {"priority_next": {"lens_id": "AGENT-BOUNDARY", "stage": "FALSIFICATION", "artifact": "Agent Permission Boundary"}},
            {},
        )
        self.assertEqual(packet["joint_focus"]["research_bias"], "GOVERNANCE")
        self.assertEqual(packet["handoff"]["guidance"]["research_bias"], "GOVERNANCE")

    def test_handoff_cannot_inherit_unknown_ai_focus(self):
        packet = joint.build_packet(
            {"weakest_next_focus": "invent-new-permissions"},
            {"priority_next": {"lens_id": "AI-CAPABILITY-DIFF", "stage": "DISCOVERY", "artifact": "Capability Diff"}},
            {},
        )
        self.assertEqual(packet["joint_focus"]["ai"], "invent-new-permissions")
        self.assertEqual(packet["handoff"]["guidance"]["ai_priority_focus"], "security")
        self.assertEqual(packet["handoff"]["authority"], "priority_only")

    def test_failed_auditability_biases_ai_priority_to_observability_only(self):
        packet = joint.build_packet(
            {"weakest_next_focus": "efficiency", "report_fingerprint": "ai-audit"},
            {"run_id": "sec-audit", "priority_next": {"lens_id": "AGENT-AUDIT", "stage": "RETEST", "artifact": "Audit Pack"}},
            {},
            {
                "track": "SEC-PORT-005",
                "status": "FAIL",
                "verification_state": "BUILDING",
                "auditability_score": 0.75,
                "actual_mutations": 2,
                "deny_reached_execution": 0,
                "gaps": ["AUD-06-structured-trace"],
                "fingerprint": "audit-gap",
                "source_run": "321",
            },
        )
        self.assertEqual(packet["joint_focus"]["ai"], "observability")
        self.assertEqual(packet["joint_focus"]["auditability_pressure"], "OBSERVABILITY_GAP")
        self.assertEqual(packet["handoff"]["guidance"]["ai_priority_focus"], "observability")
        self.assertEqual(packet["handoff"]["authority"], "priority_only")
        self.assertTrue(packet["handoff"]["constraints"]["permission_surface_unchanged"])
        self.assertTrue(packet["handoff"]["constraints"]["external_scope_unchanged"])
        self.assertIn("AUD-06-structured-trace", packet["contracts"]["ai_assist"])

    def test_passing_auditability_preserves_upstream_ai_priority(self):
        packet = joint.build_packet(
            {"weakest_next_focus": "architecture"},
            {},
            {},
            {
                "track": "SEC-PORT-005",
                "status": "PASS",
                "verification_state": "SCOPED_VERIFIED_CANDIDATE",
                "auditability_score": 1.0,
                "actual_mutations": 3,
                "deny_reached_execution": 0,
                "gaps": [],
                "fingerprint": "audit-pass",
            },
        )
        self.assertEqual(packet["joint_focus"]["ai"], "architecture")
        self.assertEqual(packet["joint_focus"]["auditability_pressure"], "REGRESSION_WATCH")
        self.assertEqual(packet["handoff"]["guidance"]["ai_priority_focus"], "architecture")

    def test_load_auditability_rejects_wrong_result_and_recovers_canonical_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "auditability-result.json"
            staged.write_text(json.dumps({"schema": "standment-llm-security-eval/v1", "status": "PASS"}), encoding="utf-8")
            source = root / "sources" / "auditability"
            source.mkdir(parents=True)
            canonical = {
                "schema": "standment-agent-auditability-evidence/v1",
                "track": "SEC-PORT-005",
                "status": "PASS",
                "verification_state": "SCOPED_VERIFIED_CANDIDATE",
                "auditability_score": 1.0,
                "actual_mutations": 8,
                "deny_reached_execution": 0,
                "fingerprint": "canonical",
                "source_run": "123",
                "gaps": [],
            }
            (source / "result.json").write_text(json.dumps(canonical), encoding="utf-8")
            loaded = joint._load_auditability(str(staged))
            self.assertEqual(loaded["schema"], "standment-agent-auditability-evidence/v1")
            self.assertEqual(loaded["track"], "SEC-PORT-005")
            self.assertEqual(loaded["fingerprint"], "canonical")

    def test_load_auditability_rejects_unrelated_result_without_canonical_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "auditability-result.json"
            staged.write_text(json.dumps({"schema": "standment-llm-security-eval/v1", "status": "PASS"}), encoding="utf-8")
            self.assertEqual(joint._load_auditability(str(staged)), {})


if __name__ == "__main__":
    unittest.main()
