#!/usr/bin/env python3
from __future__ import annotations

import unittest
from types import SimpleNamespace

import network_replica_apply
import network_replica_loop

NOW = 2_000_000_000


def _policy():
    return {
        "policy_hash": "p1",
        "grants": {
            "root.example.test": {
                "host": "root.example.test",
                "url": "https://root.example.test/",
                "expires_at": NOW + 86400,
                "allowed_methods": ["GET", "HEAD"],
                "credential_scope": "none",
                "effect": "read_only_network_contact",
                "authorization_basis": "explicit_network_root",
                "authorization_reference": "test-root",
            },
            "api.root.example.test": {
                "host": "api.root.example.test",
                "url": "https://api.root.example.test/",
                "expires_at": NOW + 86400,
                "allowed_methods": ["GET"],
                "credential_scope": "none",
                "effect": "read_only_network_contact",
                "authorization_basis": "explicit_network_root_inheritance",
                "authorization_reference": "test-root",
            },
        },
    }


class _BodyResult:
    def __init__(self, url: str):
        self.receipt = SimpleNamespace(
            provider_acknowledged=True,
            status=200,
            final_url=url,
            content_type="text/html",
            contacted_hosts=("root.example.test",),
        )

    def text(self):
        return (
            '<a href="/next">next</a>'
            '<a href="https://api.root.example.test/v2">api</a>'
            '<a href="https://outside.example.net/">outside</a>'
        )


class _Client:
    def __init__(self, policy):
        self.policy = policy
        self.calls = []

    def contact_with_body(self, url, *, method="GET", **kwargs):
        self.calls.append((url, method))
        return _BodyResult(url)


class PersistentReplicaTests(unittest.TestCase):
    def test_builds_only_exact_active_runtime_authority(self):
        discovery = {
            "discovered_urls": [
                "https://root.example.test/a",
                "https://api.root.example.test/v1",
                "https://outside.example.net/x",
            ]
        }
        result = network_replica_loop.build_replicas(_policy(), discovery, now=NOW)
        urls = {row["url"] for row in result["replicas"]}
        self.assertEqual(
            urls,
            {"https://root.example.test/a", "https://api.root.example.test/v1"},
        )
        self.assertEqual(result["held_outside_active_authority"], 1)
        self.assertEqual(result["persistence_backend"], "github_actions_artifact")

    def test_active_grants_seed_persistence_when_discovery_has_no_authorized_url(self):
        discovery = {"discovered_urls": ["https://outside.example.net/x"]}
        result = network_replica_loop.build_replicas(_policy(), discovery, now=NOW)
        urls = {row["url"] for row in result["replicas"]}
        self.assertEqual(
            urls,
            {"https://root.example.test/", "https://api.root.example.test/"},
        )
        self.assertEqual(result["held_outside_active_authority"], 1)
        self.assertGreater(result["replica_count"], 0)

    def test_previous_replica_is_refreshed_and_generation_advances(self):
        discovery = {"discovered_urls": []}
        previous = {
            "replicas": [
                {
                    "id": "net-replica-existing",
                    "generation": 7,
                    "url": "https://root.example.test/a",
                    "lease_expires_at": NOW + 1000,
                }
            ]
        }
        result = network_replica_loop.build_replicas(
            _policy(), discovery, previous=previous, now=NOW
        )
        self.assertEqual(result["replica_count"], 1)
        self.assertEqual(result["replicas"][0]["id"], "net-replica-existing")
        self.assertEqual(result["replicas"][0]["generation"], 8)

    def test_replica_executes_new_external_action_and_emits_evidence(self):
        replicas = network_replica_loop.build_replicas(
            _policy(),
            {"discovered_urls": ["https://root.example.test/a"]},
            now=NOW,
        )
        clients = []

        def factory(policy):
            client = _Client(policy)
            clients.append(client)
            return client

        result = network_replica_apply.apply_replicas(
            _policy(), replicas, now=NOW, client_factory=factory
        )
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(clients[0].calls, [("https://root.example.test/a", "GET")])
        urls = set(result["discovered_urls"])
        self.assertIn("https://root.example.test/next", urls)
        self.assertIn("https://api.root.example.test/v2", urls)
        self.assertIn("https://outside.example.net/", urls)

    def test_unauthorized_or_expired_replica_does_not_execute(self):
        replicas = {
            "replicas": [
                {
                    "id": "outside",
                    "generation": 1,
                    "url": "https://outside.example.net/x",
                    "lease_expires_at": NOW + 1000,
                    "effect": "read_only_network_contact",
                    "allowed_methods": ["GET"],
                    "credential_scope": "none",
                },
                {
                    "id": "expired",
                    "generation": 1,
                    "url": "https://root.example.test/old",
                    "lease_expires_at": NOW - 1,
                    "effect": "read_only_network_contact",
                    "allowed_methods": ["GET"],
                    "credential_scope": "none",
                },
            ]
        }
        result = network_replica_apply.apply_replicas(_policy(), replicas, now=NOW)
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["succeeded"], 0)


if __name__ == "__main__":
    unittest.main()
