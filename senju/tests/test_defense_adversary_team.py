from __future__ import annotations

import unittest
from pathlib import Path

from senju.defense_adversary_team import (
    probe_engagement,
    probe_external_contact,
    probe_scopeguard,
    run_team,
)


class DefenseAdversaryTeamTests(unittest.TestCase):
    def test_scopeguard_fuzz_has_no_surprising_behavior(self) -> None:
        findings = probe_scopeguard()
        self.assertGreaterEqual(len(findings), 1000)
        self.assertFalse([item for item in findings if not item.passed])

    def test_external_contact_boundary_cases_hold(self) -> None:
        self.assertFalse([item for item in probe_external_contact() if not item.passed])

    def test_engagement_mutations_are_rejected(self) -> None:
        self.assertFalse([item for item in probe_engagement() if not item.passed])

    def test_all_defense_layers_are_connected(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        report = run_team(repo_root)
        layers = {item.layer for item in report.findings}
        self.assertEqual(
            layers,
            {
                "scopeguard",
                "external-contact",
                "engagement",
                "execution-boundary",
                "security-guard-workflow",
                "artifact-guard",
                "autonomy-isolation",
            },
        )
        self.assertFalse(report.weaknesses)


if __name__ == "__main__":
    unittest.main()
