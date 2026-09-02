import copy
import unittest

from automation.world import consume_ai_security_handoff as consumer


def packet():
    return {
        "schema": "the-world-ai-security-joint-assist/v1",
        "status": "BUILDING",
        "assist_seed_short": "1234567890abcdefabcd",
        "handoff": {
            "schema": "the-world-ai-security-handoff/v1",
            "authority": "priority_only",
            "handoff_token": "1234567890abcdefabcd",
            "freshness": {
                "max_consumer_cycles": 2,
                "stale_behavior": "ignore_and_fall_back_to_local_evidence",
            },
            "guidance": {
                "ai_priority_focus": "efficiency",
                "security_priority_lens": "CI-PERMISSIONS",
                "security_priority_stage": "PORTFOLIO",
                "research_bias": "GOVERNANCE",
            },
            "source": {"ai_fingerprint": "ai-1", "security_run_id": "sec-1", "research_run_id": 9},
            "constraints": {
                "promotion_gate_unchanged": True,
                "permission_surface_unchanged": True,
                "external_scope_unchanged": True,
                "verification_authority_unchanged": True,
                "external_target_expansion_forbidden": True,
            },
        },
    }


class HandoffConsumerTests(unittest.TestCase):
    def test_accepts_bounded_priority_only_handoff(self):
        result = consumer.validate_packet(packet())
        self.assertEqual(result["status"], "ACCEPTED_PRIORITY_ONLY")
        self.assertEqual(result["ai_priority_focus"], "efficiency")
        self.assertEqual(result["security_priority_lens"], "CI-PERMISSIONS")
        self.assertEqual(result["max_consumer_cycles"], 2)

    def test_accepts_current_joint_assist_v2_with_same_bounded_handoff(self):
        value = packet()
        value["schema"] = "the-world-ai-security-joint-assist/v2"
        result = consumer.validate_packet(value)
        self.assertEqual(result["status"], "ACCEPTED_PRIORITY_ONLY")

    def test_rejects_unknown_assist_schema(self):
        value = packet()
        value["schema"] = "the-world-ai-security-joint-assist/v999"
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_permission_relaxation(self):
        value = packet()
        value["handoff"]["constraints"]["permission_surface_unchanged"] = False
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_external_scope_relaxation(self):
        value = packet()
        value["handoff"]["constraints"]["external_target_expansion_forbidden"] = False
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_unbounded_authority(self):
        value = packet()
        value["handoff"]["authority"] = "execute_anything"
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_unknown_ai_focus(self):
        value = packet()
        value["handoff"]["guidance"]["ai_priority_focus"] = "invent-new-permissions"
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_excess_consumer_cycles(self):
        value = packet()
        value["handoff"]["freshness"]["max_consumer_cycles"] = 3
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)

    def test_rejects_token_mismatch(self):
        value = packet()
        value["handoff"]["handoff_token"] = "ffffffffffffffffffff"
        with self.assertRaises(ValueError):
            consumer.validate_packet(value)


if __name__ == "__main__":
    unittest.main()
