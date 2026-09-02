from __future__ import annotations

import unittest

from automation.codegen.the_world_final_contract import build_final_contract


class FinalContractTests(unittest.TestCase):
    def _loop(self):
        return {
            "closed_loop": True,
            "phases": [
                "self_tuning",
                "network_policy_refresh",
                "discovery",
                "live_authority_rebuild_and_auto_renew",
                "external_action",
                "replication",
                "persistent_queue",
                "recovery_from_live_authority",
                "credentialed_external_write",
                "discover_again",
            ],
            "runtime_bootstrap": {
                "authority_source": "trusted_production_checkout",
                "required_files_present": True,
                "generated_authority_imported": False,
                "runtime_cache_may_override_owner_policy": False,
                "copied_files": [
                    {"name": "discovery_policy.json"},
                    {"name": "meta_discovery_seed.json"},
                    {"name": "network_policy_envelope.json"},
                ],
            },
            "authority": {
                "root": "explicit_owner_authority",
                "same_scope_live_grant_auto_renew": True,
                "authority_inheritance": "same_or_narrower_only",
                "checkpoint_recovery": "revalidate_live_parent_before_restore",
                "new_root_self_authorization": False,
                "revoked_authority_auto_restore": False,
                "security_self_approval": False,
            },
            "discovery": {
                "final_shared_discovery_count": 2,
                "final_authorized_count": 1,
                "final_action_ready_count": 1,
                "final_high_impact_ready_count": 1,
            },
            "actions": {
                "attempted": 2,
                "succeeded": 2,
                "failed": 0,
                "denied_before_execution": 0,
            },
            "credentialed_external_write": {
                "succeeded": True,
                "repository": "MusicJapanLLC/test",
                "provider": "github",
                "operation": "write_current_commit_status",
                "secret_persisted": False,
            },
            "rediscovery": {
                "final_shared_discovery_count": 2,
                "final_authorized_count": 1,
                "final_action_ready_count": 1,
            },
            "final_queue": {"generation": 2, "item_count": 2},
            "final_replicas": {"replica_count": 1},
            "final_lease": {"lease_count": 1},
        }

    def _registry(self):
        return {
            "owner_approved_namespaces": [
                {
                    "owner_authorized": True,
                    "repository": "MusicJapanLLC/test",
                    "recovery_workflows": ["the-world-unified-loop.yml"],
                }
            ],
            "workers": [
                {
                    "id": "the-world-unified-loop-watchdog",
                    "owner_authorized": True,
                    "recovery": {"workflow": "the-world-unified-loop.yml"},
                }
            ],
        }

    def _council(self):
        return {
            "authority_decision": {"allowed": True},
            "ai_council": {
                "effect": "allow",
                "per_host_manual_reapproval_required": False,
            },
            "invariants": {
                "hard_deny_override": False,
                "revocation_override": False,
            },
        }

    def _deployment(self):
        return {
            "environment": "production",
            "action": "deploy",
            "target_host": "kabeya-authorized-test-range.onrender.com",
            "authority_reference": "canonical:kabeya-authorized-test-range",
            "reachable": True,
            "authority_expanded": False,
            "raw_credential_inherited": False,
        }

    def _contract(self, *, loop=None, registry=None, council=None, deployment=None):
        return build_final_contract(
            loop if loop is not None else self._loop(),
            registry if registry is not None else self._registry(),
            council if council is not None else self._council(),
            deployment if deployment is not None else self._deployment(),
        )

    def test_complete_contract(self):
        contract = self._contract()
        self.assertTrue(contract["complete"])
        self.assertTrue(all(v["integrated"] for v in contract["layers"].values()))
        self.assertTrue(contract["authorization_is_primary"])
        self.assertTrue(contract["checks"]["runtime_owner_state_bootstrapped"])
        self.assertTrue(contract["checks"]["autonomous_authority_council_operational"])
        self.assertTrue(contract["checks"]["owner_authorized_external_deployment_operational"])
        self.assertEqual(
            contract["discovery_target_rule"],
            "inside_existing_owner_envelope: discovered == authorized",
        )
        self.assertTrue(contract["target_activation"]["target_to_external_action_is_operational"])
        self.assertTrue(contract["target_activation"]["runtime_owner_policy_bootstrapped"])

    def test_missing_runtime_bootstrap_breaks_contract(self):
        loop = self._loop()
        loop.pop("runtime_bootstrap")
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["runtime_owner_state_bootstrapped"])
        self.assertFalse(contract["layers"]["discovery"]["integrated"])
        self.assertFalse(contract["layers"]["authorization"]["integrated"])

    def test_runtime_bootstrap_cannot_import_generated_authority(self):
        loop = self._loop()
        loop["runtime_bootstrap"]["generated_authority_imported"] = True
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["runtime_owner_state_bootstrapped"])

    def test_runtime_cache_cannot_override_owner_policy(self):
        loop = self._loop()
        loop["runtime_bootstrap"]["runtime_cache_may_override_owner_policy"] = True
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["runtime_owner_state_bootstrapped"])

    def test_new_root_self_mint_breaks_contract(self):
        loop = self._loop()
        loop["authority"]["new_root_self_authorization"] = True
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["no_new_root_self_mint"])

    def test_cross_repo_credential_write_breaks_contract(self):
        loop = self._loop()
        loop["credentialed_external_write"]["repository"] = "someone/else"
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["credentialed_write_is_current_repo_status"])

    def test_watchdog_is_required(self):
        registry = self._registry()
        registry["workers"] = []
        contract = self._contract(registry=registry)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["independent_watchdog_registered"])

    def test_zero_authorized_targets_breaks_contract(self):
        loop = self._loop()
        loop["discovery"]["final_authorized_count"] = 0
        loop["discovery"]["final_action_ready_count"] = 0
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["owner_envelope_authorized_target_present"])

    def test_every_authorized_target_must_be_action_ready(self):
        loop = self._loop()
        loop["discovery"]["final_authorized_count"] = 2
        loop["discovery"]["final_action_ready_count"] = 1
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["every_authorized_target_is_action_ready"])

    def test_zero_external_action_success_breaks_contract(self):
        loop = self._loop()
        loop["actions"]["succeeded"] = 0
        loop["actions"]["failed"] = 2
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["discovery_external_action_succeeded"])
        self.assertFalse(contract["layers"]["execution"]["integrated"])

    def test_zero_replica_or_lease_breaks_contract(self):
        loop = self._loop()
        loop["final_replicas"]["replica_count"] = 0
        loop["final_lease"]["lease_count"] = 0
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["authorized_replication_present"])
        self.assertFalse(contract["checks"]["live_authority_leases_present"])

    def test_empty_persistent_queue_breaks_contract(self):
        loop = self._loop()
        loop["final_queue"]["item_count"] = 0
        contract = self._contract(loop=loop)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["persistent_queue_present"])

    def test_council_must_be_operational(self):
        council = self._council()
        council["authority_decision"]["allowed"] = False
        council["ai_council"]["effect"] = "deny"
        contract = self._contract(council=council)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["autonomous_authority_council_operational"])
        self.assertFalse(contract["layers"]["authorization"]["integrated"])

    def test_council_cannot_override_hard_deny(self):
        council = self._council()
        council["invariants"]["hard_deny_override"] = True
        contract = self._contract(council=council)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["autonomous_authority_council_operational"])

    def test_deployment_must_use_exact_owner_root(self):
        deployment = self._deployment()
        deployment["target_host"] = "unrelated.example"
        contract = self._contract(deployment=deployment)
        self.assertFalse(contract["complete"])
        self.assertFalse(contract["checks"]["owner_authorized_external_deployment_operational"])
        self.assertFalse(contract["layers"]["execution"]["integrated"])


if __name__ == "__main__":
    unittest.main()
