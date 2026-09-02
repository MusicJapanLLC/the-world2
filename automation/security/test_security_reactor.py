from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from automation.security.security_reactor import MAX_HISTORY, run_session
except ModuleNotFoundError:
    # The portfolio R&D workflow intentionally runs tests from automation/security,
    # while other CI paths may invoke this module from the repository root.
    from security_reactor import MAX_HISTORY, run_session


PROGRAM = {
    "tracks": [
        {
            "id": "SEC-PORT-004",
            "title": "Auth / tenant / RLS defensive evidence kit",
            "priority": 200,
            "senju_focus": "robustness",
            "hypothesis": "Tenant isolation is reproducible with defensive fixtures.",
            "deliverable": "Inspectable auth and isolation evidence.",
            "customer_usefulness": "Reduces authorization mistakes.",
            "evidence_files": [
                "standment-security/evidence-packs/auth-tenant-rls/README.md",
                "standment-security/evidence-packs/auth-tenant-rls/retest.md",
            ],
        },
        {
            "id": "SEC-PORT-006",
            "title": "Incident Readiness",
            "priority": 180,
            "senju_focus": "learning",
            "hypothesis": "Recovery evidence can be reproduced.",
            "deliverable": "Recovery evidence pack.",
            "customer_usefulness": "Improves incident readiness.",
            "evidence_files": [
                "standment-security/evidence-packs/incident-readiness/README.md",
            ],
        },
    ]
}


def make_repo(root: Path) -> None:
    (root / "standment-security").mkdir(parents=True, exist_ok=True)
    (root / "standment-security/security_portfolio_program.json").write_text(
        json.dumps(PROGRAM, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "PORTFOLIO.md").write_text("# Portfolio\n", encoding="utf-8")


class SecurityReactorTests(unittest.TestCase):
    def test_reactor_materializes_building_artifacts_without_verification_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_repo(root)
            result = run_session(
                root=root,
                program_rel="standment-security/security_portfolio_program.json",
                portfolio_rel="PORTFOLIO.md",
                state_rel="standment-security/state/security-reactor.json",
                rounds=3,
                sleep_seconds=0,
                session_id="test-1",
            )
            self.assertFalse(result["verification_claimed"])
            self.assertEqual(result["external_targets_touched"], 0)
            self.assertEqual(result["rounds_completed"], 3)
            self.assertTrue((root / "standment-security/SECURITY_REACTOR.md").exists())
            self.assertTrue((root / "standment-security/reactor-candidates/latest.json").exists())
            created = list(root.rglob("README.md"))
            self.assertTrue(created)
            for path in created:
                text = path.read_text(encoding="utf-8")
                self.assertIn("BUILDING", text)
                self.assertNotIn("状態: VERIFIED", text)

    def test_failure_memory_penalizes_no_delta_repetition_and_history_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_repo(root)
            for i in range(24):
                run_session(
                    root=root,
                    program_rel="standment-security/security_portfolio_program.json",
                    portfolio_rel="PORTFOLIO.md",
                    state_rel="standment-security/state/security-reactor.json",
                    rounds=3,
                    sleep_seconds=0,
                    session_id=f"test-{i}",
                )
            state = json.loads((root / "standment-security/state/security-reactor.json").read_text(encoding="utf-8"))
            self.assertLessEqual(len(state["history"]), MAX_HISTORY)
            self.assertLessEqual(len(state["failure_memory"]), 32)
            self.assertTrue(any(v > 0 for v in state["failure_memory"].values()))

    def test_reactor_forces_multiple_research_modes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_repo(root)
            result = run_session(
                root=root,
                program_rel="standment-security/security_portfolio_program.json",
                portfolio_rel="PORTFOLIO.md",
                state_rel="standment-security/state/security-reactor.json",
                rounds=4,
                sleep_seconds=0,
                session_id="test-modes",
            )
            modes = {row["mode"] for row in result["records"]}
            self.assertGreaterEqual(len(modes), 4)
            self.assertIn("REFRAME_AND_COUNTEREVIDENCE", modes)
            self.assertIn("INDEPENDENT_RETEST", modes)
            self.assertIn("SWITCH_EVIDENCE_PATH", modes)

    def test_reactor_scratch_is_artifact_only_and_never_git_persistence(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/reports/standment-security-rnd/", gitignore)

    def test_round_and_sleep_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_repo(root)
            with self.assertRaises(ValueError):
                run_session(
                    root=root,
                    program_rel="standment-security/security_portfolio_program.json",
                    portfolio_rel="PORTFOLIO.md",
                    state_rel="standment-security/state/security-reactor.json",
                    rounds=17,
                    sleep_seconds=0,
                    session_id="too-many",
                )
            with self.assertRaises(ValueError):
                run_session(
                    root=root,
                    program_rel="standment-security/security_portfolio_program.json",
                    portfolio_rel="PORTFOLIO.md",
                    state_rel="standment-security/state/security-reactor.json",
                    rounds=1,
                    sleep_seconds=301,
                    session_id="too-slow",
                )


if __name__ == "__main__":
    unittest.main()
