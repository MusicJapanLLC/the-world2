from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.network_policy_expansion import run_network_policy_expansion


class NetworkPolicyExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "automation" / "codegen" / "meta_state"
        self.state.mkdir(parents=True)
        (self.state / "discovery_policy.json").write_text(
            json.dumps({
                "schema": "meta-discovery-policy/v1",
                "trusted_roots": ["owned.example.com"],
                "promotion": {"allowed_methods": ["GET", "HEAD"]},
            }),
            encoding="utf-8",
        )
        (self.state / "network_policy_envelope.json").write_text(
            json.dumps({
                "schema": "meta-network-policy-envelope/v1",
                "authorized_roots": ["owned.example.com"],
                "inherit_subdomains": True,
                "ttl_seconds": 3600,
                "max_dynamic_hosts": 8,
            }),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_input(self, value: object, name: str = "external.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_external_response_updates_runtime_allowlist_inside_explicit_root(self) -> None:
        source = self._write_input({
            "response": {
                "message": "this host is needed",
                "links": [
                    "https://api.owned.example.com/v1/status",
                    "https://unrelated.example.net/docs",
                ],
            }
        })
        result = run_network_policy_expansion(
            self.state,
            repo_root=self.root,
            input_paths=[source],
        )
        self.assertEqual(result["applied_host_count"], 1)
        self.assertEqual(result["held_host_count"], 1)
        self.assertEqual(result["allow_hosts"], ["api.owned.example.com"])

        runtime = json.loads((self.state / "network_policy_runtime.json").read_text())
        grant = runtime["grants"]["api.owned.example.com"]
        self.assertEqual(grant["allowed_methods"], ["GET", "HEAD"])
        self.assertEqual(grant["credential_scope"], "none")
        self.assertEqual(grant["authorization_basis"], "explicit_network_root")
        self.assertTrue(grant["external_input_drove_policy_change"])

        requests = json.loads((self.state / "network_policy_expansion_requests.json").read_text())
        self.assertEqual(requests["requests"][0]["host"], "unrelated.example.net")
        self.assertEqual(requests["requests"][0]["decision"], "held_for_authority")

    def test_agent_finding_reuses_active_explicit_exact_grant(self) -> None:
        now = int(time.time())
        (self.state / "authority_reviewed_grants.json").write_text(
            json.dumps({
                "schema": "meta-authority-reviewed-grants/v1",
                "hosts": {
                    "exact.partner.example": {
                        "expires_at": now + 1800,
                        "credential_scope": "none",
                        "effect": "read_only",
                        "allowed_methods": ["GET", "HEAD"],
                        "owner_authorization": "explicit",
                    }
                },
            }),
            encoding="utf-8",
        )
        source = self._write_input({
            "agent_finding": {
                "host": "exact.partner.example",
                "reason": "network dependency discovered",
            }
        }, "agent.json")
        result = run_network_policy_expansion(
            self.state,
            repo_root=self.root,
            input_paths=[source],
        )
        self.assertIn("exact.partner.example", result["allow_hosts"])
        runtime = json.loads((self.state / "network_policy_runtime.json").read_text())
        self.assertEqual(
            runtime["grants"]["exact.partner.example"]["authorization_basis"],
            "active_explicit_exact_grant",
        )

    def test_exact_grant_does_not_authorize_new_subdomain(self) -> None:
        now = int(time.time())
        (self.state / "authority_reviewed_grants.json").write_text(
            json.dumps({
                "schema": "meta-authority-reviewed-grants/v1",
                "hosts": {
                    "exact.partner.example": {
                        "expires_at": now + 1800,
                        "credential_scope": "none",
                        "effect": "read_only",
                        "allowed_methods": ["GET"],
                        "owner_authorization": "explicit",
                    }
                },
            }),
            encoding="utf-8",
        )
        source = self._write_input({"host": "child.exact.partner.example"})
        result = run_network_policy_expansion(
            self.state,
            repo_root=self.root,
            input_paths=[source],
        )
        self.assertEqual(result["applied_host_count"], 0)
        self.assertEqual(result["held_host_count"], 1)

    def test_previous_runtime_grant_is_revalidated_before_preservation(self) -> None:
        now = int(time.time())
        previous = self.root / "previous.json"
        previous.write_text(
            json.dumps({
                "schema": "meta-network-policy-runtime/v1",
                "grants": {
                    "old.unrelated.example": {
                        "host": "old.unrelated.example",
                        "expires_at": now + 3000,
                        "allowed_methods": ["GET", "HEAD"],
                        "credential_scope": "none",
                    },
                    "kept.owned.example.com": {
                        "host": "kept.owned.example.com",
                        "expires_at": now + 3000,
                        "allowed_methods": ["GET", "HEAD"],
                        "credential_scope": "none",
                    },
                },
            }),
            encoding="utf-8",
        )
        result = run_network_policy_expansion(
            self.state,
            repo_root=self.root,
            previous_path=previous,
        )
        self.assertEqual(result["allow_hosts"], ["kept.owned.example.com"])

    def test_http_and_ip_literal_evidence_do_not_expand_policy(self) -> None:
        source = self._write_input({
            "links": [
                "http://api.owned.example.com/plain",
                "https://127.0.0.1/private",
            ]
        })
        result = run_network_policy_expansion(
            self.state,
            repo_root=self.root,
            input_paths=[source],
        )
        self.assertEqual(result["applied_host_count"], 0)
        self.assertEqual(result["held_host_count"], 0)


if __name__ == "__main__":
    unittest.main()
