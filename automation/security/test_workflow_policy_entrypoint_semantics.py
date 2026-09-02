from __future__ import annotations

import unittest

from automation.security import workflow_policy as policy
from automation.security import workflow_policy_entrypoint as entrypoint


class AgentFactorySemanticPolicyTests(unittest.TestCase):
    def setUp(self):
        self.name = "the-world-agent-factory.yml"
        self.original = policy.WORKFLOWS[self.name]

    def tearDown(self):
        policy.WORKFLOWS[self.name] = self.original

    def test_current_factory_semantics_pass_without_title_dependency(self):
        body = self.original.replace(entrypoint.LEGACY_FACTORY_LABEL, "renamed human readable validation step")
        policy.WORKFLOWS[self.name] = body
        self.assertEqual(self.name, entrypoint.validate_agent_factory_semantic_contract())
        self.assertIn(entrypoint.LEGACY_FACTORY_LABEL, policy.WORKFLOWS[self.name])

    def test_permission_expansion_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original + "\n  issues: write\n"
        with self.assertRaises(SystemExit):
            entrypoint.validate_agent_factory_semantic_contract()

    def test_extra_champion_write_grant_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original + "\n# accidental duplicate --allow-tool=write\n"
        with self.assertRaises(SystemExit):
            entrypoint.validate_agent_factory_semantic_contract()

    def test_shell_url_denial_regression_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original.replace("--deny-tool=shell", "--deny-tool=not-shell")
        with self.assertRaises(SystemExit):
            entrypoint.validate_agent_factory_semantic_contract()

    def test_security_validation_removal_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original.replace(
            "python -m unittest discover -s automation/security -p 'test_*.py'",
            "echo security-validation-removed",
        )
        with self.assertRaises(SystemExit):
            entrypoint.validate_agent_factory_semantic_contract()


class MadlabEvolutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.name = "madlab-world-evolution.yml"
        self.original = policy.WORKFLOWS[self.name]

    def tearDown(self):
        policy.WORKFLOWS[self.name] = self.original

    def test_madlab_evolution_lane_passes_current_workflow(self):
        self.assertEqual(self.name, entrypoint.validate_madlab_evolution_lane())

    def test_madlab_cron_drift_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original.replace("cron: '17 */6 * * *'", "cron: '17 */3 * * *'")
        with self.assertRaises(SystemExit):
            entrypoint.validate_madlab_evolution_lane()

    def test_madlab_forbidden_permission_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original + "\n  contents: write\n"
        with self.assertRaises(SystemExit):
            entrypoint.validate_madlab_evolution_lane()

    def test_madlab_missing_required_guardrail_fails_closed(self):
        policy.WORKFLOWS[self.name] = self.original.replace(
            "Never weaken ownership, authorization, or approval boundaries.",
            "echo relaxed-boundaries",
        )
        with self.assertRaises(SystemExit):
            entrypoint.validate_madlab_evolution_lane()


if __name__ == "__main__":
    unittest.main()
