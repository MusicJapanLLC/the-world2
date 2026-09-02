from pathlib import Path
import tempfile
import unittest

from senju.defense_adversary_direct import run_direct


class DirectDefenseAdversaryTests(unittest.TestCase):
    def test_runs_all_real_layers(self) -> None:
        report = run_direct(scope_cases=64, seed=7)
        layers = {item.layer for item in report.findings}
        self.assertEqual(
            layers,
            {
                "scopeguard",
                "engagement-json",
                "external-contact",
                "offense-first",
                "security-guard-workflow",
                "artifact-guard",
                "autonomy-engine",
            },
        )
        self.assertGreater(len(report.findings), 64)


if __name__ == "__main__":
    unittest.main()
