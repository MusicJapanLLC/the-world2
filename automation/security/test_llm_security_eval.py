import json
import unittest
from pathlib import Path

from automation.security.llm_security_eval import evaluate_suite


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "standment-security" / "ai-security" / "fixtures"


class LlmSecurityEvalTests(unittest.TestCase):
    def load(self, name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_vulnerable_baseline_exposes_boundary_failures(self):
        report = evaluate_suite(self.load("llm-security-vulnerable.json"))
        self.assertLess(report["pass_rate"], 1.0)
        self.assertGreater(report["failed"], 0)
        self.assertGreater(report["high_risk_violation_count"], 0)

    def test_hardened_reference_passes_all_synthetic_cases(self):
        report = evaluate_suite(self.load("llm-security-hardened.json"))
        self.assertEqual(report["pass_rate"], 1.0)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["high_risk_violation_count"], 0)

    def test_hardened_reference_materially_improves_same_condition_suite(self):
        before = evaluate_suite(self.load("llm-security-vulnerable.json"))
        after = evaluate_suite(self.load("llm-security-hardened.json"))
        self.assertGreater(after["pass_rate"], before["pass_rate"])
        self.assertLess(after["high_risk_violation_count"], before["high_risk_violation_count"])
        self.assertEqual(before["total"], after["total"])


if __name__ == "__main__":
    unittest.main()
