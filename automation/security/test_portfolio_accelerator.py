import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import portfolio_accelerator


JST = ZoneInfo("Asia/Tokyo")


class PortfolioAcceleratorTests(unittest.TestCase):
    def program(self):
        return {
            "mission": "test mission",
            "tracks": [
                {
                    "id": "SEC-PORT-001",
                    "title": "Scan",
                    "priority": 1400,
                    "senju_focus": "robustness",
                    "customer_usefulness": "buyer sees before/after",
                    "evidence_files": ["a.md", "b.md"],
                },
                {
                    "id": "SEC-PORT-010",
                    "title": "LLM Harness",
                    "priority": 1140,
                    "senju_focus": "learning",
                    "customer_usefulness": "AI team gets regression evidence",
                    "evidence_files": ["c.md"],
                },
            ],
        }

    def test_counts_whitehat_candidates_without_claiming_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("proof", encoding="utf-8")
            candidate_dir = root / "standment-security/whitehat-candidates"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "x.md").write_text("- track: `SEC-PORT-001` — Scan\n", encoding="utf-8")
            report = portfolio_accelerator.build(self.program(), root, candidate_dir, {}, datetime.now(JST))
            row = next(r for r in report["all_tracks"] if r["id"] == "SEC-PORT-001")
            self.assertEqual(row["whitehat_candidates"], 1)
            self.assertFalse(report["verification_claimed"])
            self.assertEqual(report["company_priority"], "P0")

    def test_rotates_after_three_stagnant_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = {
                "primary": {"id": "SEC-PORT-001", "status": "ABSENT", "evidence_ratio": 0.0, "whitehat_candidates": 0},
                "stagnation_streak": 2,
            }
            report = portfolio_accelerator.build(self.program(), root, root / "none", previous, datetime.now(JST))
            self.assertTrue(report["rotated"])
            self.assertEqual(report["primary"]["id"], "SEC-PORT-010")
            self.assertEqual(report["stagnation_streak"], 0)

    def test_ai_native_lane_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = portfolio_accelerator.build(self.program(), root, root / "none", {}, datetime.now(JST))
            self.assertEqual(report["ai_native_lane"]["id"], "SEC-PORT-010")

    def test_slack_payload_uses_rnd_channel_and_truth_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = portfolio_accelerator.build(self.program(), root, root / "none", {}, datetime.now(JST))
            payload = portfolio_accelerator.slack_payload(report, "standment-security/PORTFOLIO_ACCELERATION.md")
            self.assertEqual(payload["channel_id"], "C0BTFSCDDE1")
            for label in ("WHAT CHANGED", "PORTFOLIO DELTA", "WHY IT MATTERS", "SENJU", "TRUTH", "NEXT MOVE"):
                self.assertIn(label, payload["message"])


if __name__ == "__main__":
    unittest.main()
