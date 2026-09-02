#!/usr/bin/env python3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import standment_defensive_intel as intel


class DefensiveIntelTests(unittest.TestCase):
    def test_control_audit_is_owned_repo_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in intel.OWNED_CONTROL_FILES.values():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("evidence\n", encoding="utf-8")
            audit = intel.audit_owned_controls(root)
            self.assertEqual(audit["coverage"], 1.0)
            self.assertEqual(audit["missing"], [])

    def test_research_seed_contains_no_execution_target_fields(self):
        sample = [{"source": "CISA KEV", "id": "CVE-2099-0001", "date": "2099-01-01"}]
        audit = {"missing": [], "coverage": 1.0}
        seed = intel.build_research_seed(sample, audit, datetime(2099, 1, 2, tzinfo=timezone.utc))
        forbidden = {"target", "url", "host", "network", "scope", "permission", "secret", "credential", "exploit", "victim"}
        self.assertFalse(set(seed) & forbidden)
        self.assertEqual(seed["focus"], "learning")
        self.assertGreaterEqual(seed["candidate_count"], 3)
        self.assertLessEqual(seed["candidate_count"], 9)

    def test_missing_owned_evidence_wins_over_external_signal(self):
        seed = intel.build_research_seed(
            [{"source": "CISA KEV", "id": "CVE-2099-0001", "date": "2099-01-01"}],
            {"missing": ["security/example.md"], "coverage": 0.9},
            datetime(2099, 1, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(seed["focus"], "robustness")
        self.assertIn("Owned defensive-control evidence is incomplete", seed["problem"])

    def test_run_writes_human_and_machine_evidence_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            payload = intel.run(
                root,
                out,
                public_intel=[{"source": "GitHub Advisory Database", "id": "GHSA-test", "date": "2099-01-01", "summary": "test"}],
                errors=[],
            )
            self.assertTrue((out / "intel.json").exists())
            self.assertTrue((out / "intel.md").exists())
            self.assertTrue((out / "research-seed.json").exists())
            self.assertEqual(payload["boundary"], "passive-public-and-owned-authorized-only")


if __name__ == "__main__":
    unittest.main()
