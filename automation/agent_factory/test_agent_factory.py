import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import factory
import local_worker
import policy
import tournament


class AgentFactoryTests(unittest.TestCase):
    def _root(self, priority=2000):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "value-lab").mkdir()
        (root / "standment-security").mkdir()
        (root / "automation/security").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "value-lab/research_queue.json").write_text(json.dumps({
            "active": [{
                "research_id": "RND-STANDMENT-SECURITY-PORTFOLIO-001",
                "title": "Security portfolio",
                "problem": "Missing reproducible customer evidence",
                "hypothesis": "Evidence-first parallel research improves proof quality",
                "focus": "efficiency",
                "priority": priority,
            }]
        }), encoding="utf-8")
        (root / "standment-security/security_portfolio_program.json").write_text(json.dumps({
            "tracks": [{
                "id": "SEC-PORT-001",
                "title": "Security Scan case study",
                "priority": 1000,
                "hypothesis": "dogfood proof improves credibility",
                "deliverable": "before/after evidence pack",
                "evidence_files": ["standment-security/SECURITY_BASELINE.md"],
            }]
        }), encoding="utf-8")
        for path in [
            "standment-security/SECURITY_BASELINE.md",
            "standment-security/CONTROL_EVIDENCE_TEMPLATE.md",
            "standment-security/ELITE_WHITEHAT_CELL.md",
            "automation/security/portfolio_rnd.py",
            "automation/security/test_portfolio_rnd.py",
            ".github/workflows/standment-security-portfolio-rnd.yml",
        ]:
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture\n", encoding="utf-8")
        return tmp, root

    def test_dynamic_swarm_has_mandatory_independent_roles(self):
        tmp, root = self._root()
        self.addCleanup(tmp.cleanup)
        plan = factory.build_plan(root, "42")
        self.assertEqual(plan["agent_count"], 12)
        self.assertLessEqual(plan["max_parallel"], 5)
        roles = {x["role"] for x in plan["agents"]}
        for role in {"evidence_hunter", "red_skeptic", "replicator", "test_engineer", "systems_engineer", "elite_whitehat"}:
            self.assertIn(role, roles)
        whitehat = next(x for x in plan["agents"] if x["role"] == "elite_whitehat")
        self.assertEqual(whitehat["stance"], "RED")
        self.assertEqual(plan["whitehat_contract"]["mandatory_role"], "elite_whitehat")
        self.assertFalse(plan["forge"]["direct_main_push"])
        self.assertTrue(plan["forge"]["pr_required"])

    def test_lower_priority_swarm_still_keeps_whitehat(self):
        tmp, root = self._root(priority=100)
        self.addCleanup(tmp.cleanup)
        plan = factory.build_plan(root, "43")
        self.assertGreaterEqual(plan["agent_count"], 7)
        self.assertLessEqual(plan["agent_count"], 9)
        self.assertIn("elite_whitehat", {x["role"] for x in plan["agents"]})

    def test_explicit_track_progression_prefers_requested_track_and_fails_soft(self):
        program = {
            "tracks": [
                {"id": "AI-DEV-001", "priority": 1000},
                {"id": "AI-DEV-002", "priority": 950},
            ]
        }
        selected = factory._track_by_id(program, "AI-DEV-002")
        self.assertEqual(selected["id"], "AI-DEV-002")
        fallback = factory._track_by_id(program, "AI-DEV-DOES-NOT-EXIST")
        self.assertEqual(fallback["id"], "AI-DEV-001")

    def test_prompt_is_bounded_and_json_only(self):
        tmp, root = self._root()
        self.addCleanup(tmp.cleanup)
        plan = factory.build_plan(root, "44")
        slot = next(x["slot"] for x in plan["agents"] if x["role"] == "elite_whitehat")
        text = factory._prompt(plan, slot)
        self.assertIn('"schema": "agent-factory-worker/v1"', text)
        self.assertIn("Return ONE JSON object only", text)
        self.assertIn("Do not propose third-party targeting", text)
        self.assertIn("ELITE WHITE-HAT CONTRACT", text)
        self.assertIn("remediation and retest criteria", text)

    def test_local_fallback_supports_elite_whitehat(self):
        tmp, root = self._root()
        self.addCleanup(tmp.cleanup)
        plan = factory.build_plan(root, "45")
        slot = next(x["slot"] for x in plan["agents"] if x["role"] == "elite_whitehat")
        worker = local_worker.build_worker(root, plan, slot)
        self.assertEqual(worker["role"], "elite_whitehat")
        self.assertGreaterEqual(len(worker["evidence_refs"]), 3)
        self.assertIn("authorized", worker["observations"][-1])
        self.assertGreaterEqual(len(worker["proposed_change"]["tests"]), 3)

    def _valid_worker(self, agent_id="AF-1-00", role="evidence_hunter", summary="Improve evidence manifest"):
        return {
            "schema": "agent-factory-worker/v1",
            "agent_id": agent_id,
            "role": role,
            "stance": "INDEPENDENT",
            "hypothesis": "Adding a deterministic manifest makes reruns easier to compare",
            "evidence_refs": [
                "standment-security/CONTROL_EVIDENCE_TEMPLATE.md",
                "automation/security/portfolio_rnd.py",
                "value-lab/research_queue.json",
            ],
            "observations": ["Evidence exists but comparison is manual", "Current artifact has a stable contract"],
            "counterevidence": ["If current artifact already has deterministic hashing this change adds little"],
            "proposed_change": {
                "summary": summary,
                "allowed_paths": ["automation/security/portfolio_rnd.py"],
                "tests": ["run portfolio_rnd unit tests", "re-run twice and compare manifest"],
                "expected_delta": "repeated evidence runs become mechanically comparable",
                "rollback": "revert the single file change",
            },
            "limitations": ["does not prove customer demand"],
        }

    def test_normalizer_rejects_url_evidence_and_factory_self_edit(self):
        plan = {"agents": [{"agent_id": "AF-1-00", "role": "evidence_hunter", "stance": "INDEPENDENT"}]}
        row = self._valid_worker()
        row["evidence_refs"] = ["https://example.com"]
        row["proposed_change"]["allowed_paths"] = ["automation/agent_factory/factory.py"]
        normalized = tournament.normalize(plan, 0, json.dumps(row))
        self.assertFalse(normalized["eligible"])
        self.assertIn("unsafe_evidence_ref", normalized["reasons"])
        self.assertIn("forbidden_change_path", normalized["reasons"])

    def test_tournament_rewards_evidence_counterevidence_and_tests(self):
        plan = {
            "agents": [
                {"agent_id": "AF-1-00", "role": "evidence_hunter", "stance": "INDEPENDENT"},
                {"agent_id": "AF-1-01", "role": "red_skeptic", "stance": "RED"},
            ]
        }
        strong = tournament.normalize(plan, 0, json.dumps(self._valid_worker()))
        weak_payload = self._valid_worker("AF-1-01", "red_skeptic", "Small test")
        weak_payload["evidence_refs"] = ["docs/example.md"]
        weak_payload["observations"] = []
        weak_payload["counterevidence"] = ["could already exist"]
        weak_payload["proposed_change"]["tests"] = ["run one test"]
        weak_payload["limitations"] = []
        weak = tournament.normalize(plan, 1, json.dumps(weak_payload))
        result = tournament.tournament([weak, strong])
        self.assertEqual(result["champion"]["agent_id"], "AF-1-00")
        self.assertTrue(result["promotion_ready"])

    def test_invalid_workers_cannot_promote(self):
        result = tournament.tournament([
            {"agent_id": "bad", "eligible": False, "score": 99, "reasons": ["unsafe"]}
        ])
        self.assertIsNone(result["champion"])
        self.assertFalse(result["promotion_ready"])

    def test_forge_prompt_blocks_control_plane_self_modification(self):
        result = {
            "promotion_ready": True,
            "champion": {
                "agent_id": "AF-1-00", "role": "evidence_hunter", "score": 88,
                "proposal": {
                    "hypothesis": "h", "evidence_refs": ["docs/x.md"], "counterevidence": ["c"],
                    "limitations": ["l"], "proposed_change": self._valid_worker()["proposed_change"],
                }
            }
        }
        text = tournament.forge_prompt({"mission": {"research_id": "RND-X"}}, result)
        self.assertIn("Do NOT modify .github/", text)
        self.assertIn("automation/agent_factory/", text)
        self.assertIn("Do not push, merge, publish", text)

    def test_policy_allows_only_bounded_product_paths(self):
        with mock.patch.object(policy, "_git") as git:
            git.side_effect = [
                "automation/security/portfolio_rnd.py\ndocs/agent-note.md\n",
                "20\t3\tautomation/security/portfolio_rnd.py\n10\t1\tdocs/agent-note.md\n",
            ]
            result = policy.inspect_diff("HEAD")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["file_count"], 2)

    def test_policy_blocks_factory_and_workflow_edits(self):
        with mock.patch.object(policy, "_git") as git:
            git.side_effect = [
                ".github/workflows/x.yml\nautomation/agent_factory/factory.py\n",
                "1\t0\t.github/workflows/x.yml\n1\t0\tautomation/agent_factory/factory.py\n",
            ]
            result = policy.inspect_diff("HEAD")
        self.assertFalse(result["allowed"])
        self.assertTrue(any(x.startswith("blocked_path:") for x in result["violations"]))


if __name__ == "__main__":
    unittest.main()
