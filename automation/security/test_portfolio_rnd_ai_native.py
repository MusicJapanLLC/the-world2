import tempfile
import unittest
from pathlib import Path

import portfolio_rnd


class PortfolioRndAiNativeStatusTests(unittest.TestCase):
    def test_direct_ai_security_artifact_upgrades_absent_index_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = Path("standment-security/ai-security/llm-security-eval-harness.md")
            path = root / rel
            path.parent.mkdir(parents=True)
            path.write_text("# LLM Security Evaluation Harness\n\nStatus: **BUILDING**\n", encoding="utf-8")

            track = {
                "id": "SEC-PORT-010",
                "title": "LLM Security Evaluation Harness",
                "priority": 1140,
                "senju_focus": "learning",
                "hypothesis": "bounded evals improve evidence quality",
                "deliverable": "eval harness",
                "customer_usefulness": "replayable AI security regression evidence",
                "evidence_files": [str(rel)],
            }
            row = portfolio_rnd.inspect_track(root, "# portfolio without this section\n", track)

            self.assertEqual(row["portfolio_index_status"], "ABSENT")
            self.assertEqual(row["artifact_status"], "BUILDING")
            self.assertEqual(row["portfolio_status"], "BUILDING")
            self.assertEqual(row["evidence_ratio"], 1.0)

    def test_verified_index_is_not_downgraded_by_building_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = Path("standment-security/ai-security/llm-security-eval-harness.md")
            path = root / rel
            path.parent.mkdir(parents=True)
            path.write_text("# Harness\n\nStatus: **BUILDING**\n", encoding="utf-8")
            portfolio = "## LLM Security Evaluation Harness\n\n状態: VERIFIED\n"
            track = {
                "id": "SEC-PORT-010",
                "title": "LLM Security Evaluation Harness",
                "priority": 1140,
                "senju_focus": "learning",
                "hypothesis": "h",
                "deliverable": "d",
                "customer_usefulness": "u",
                "evidence_files": [str(rel)],
            }
            row = portfolio_rnd.inspect_track(root, portfolio, track)
            self.assertEqual(row["portfolio_status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
