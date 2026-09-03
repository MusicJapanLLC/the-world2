#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import network_policy_apply
import network_policy_authorized_discovery
import network_policy_seed


class _Receipt:
    def __init__(self, *, status=200, final_url="https://root.example.test/", content_type="text/html"):
        self.provider_acknowledged = 200 <= status < 400
        self.status = status
        self.final_url = final_url
        self.contacted_hosts = ("root.example.test",)
        self.content_type = content_type


class _Result:
    def __init__(self, text: str):
        self.receipt = _Receipt()
        self._text = text

    def text(self):
        return self._text


class _FallbackClient:
    def __init__(self, policy):
        self.policy = policy
        self.calls = []

    def contact(self, url, *, method="GET", **kwargs):
        self.calls.append((url, method))
        if method == "HEAD":
            raise RuntimeError("HEAD unsupported")
        return _Receipt(status=200, final_url=url)


class _DiscoveryClient:
    def __init__(self, policy):
        self.policy = policy

    def contact_with_body(self, url, *, method="GET", **kwargs):
        return _Result(
            '<a href="/inside">inside</a>'
            '<a href="https://api.root.example.test/v1">subdomain</a>'
            '<a href="https://unrelated.example.net/">outside</a>'
        )


class NetworkPolicyAccelerationTests(unittest.TestCase):
    def test_apply_falls_back_from_head_to_get(self):
        doc = {
            "policy_hash": "abc",
            "grants": {
                "root.example.test": {
                    "host": "root.example.test",
                    "url": "https://root.example.test/",
                    "expires_at": 4102444800,
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                    "effect": "read_only_network_contact",
                    "authorization_basis": "explicit_network_root",
                }
            },
        }
        audit = network_policy_apply.apply_runtime_policy(
            doc,
            client_factory=lambda policy: _FallbackClient(policy),
        )
        self.assertEqual(audit["attempted"], 1)
        self.assertEqual(audit["succeeded"], 1)
        self.assertEqual(audit["results"][0]["method"], "GET")
        self.assertEqual([a["method"] for a in audit["results"][0]["attempts"]], ["HEAD", "GET"])

    def test_authorized_response_becomes_policy_evidence(self):
        doc = {
            "grants": {
                "root.example.test": {
                    "host": "root.example.test",
                    "url": "https://root.example.test/",
                    "expires_at": 4102444800,
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                }
            }
        }
        with patch.object(network_policy_authorized_discovery, "ExternalContactClient", _DiscoveryClient):
            result = network_policy_authorized_discovery.run_discovery(doc)
        urls = set(result["discovered_urls"])
        self.assertIn("https://root.example.test/inside", urls)
        self.assertIn("https://api.root.example.test/v1", urls)
        self.assertIn("https://unrelated.example.net/", urls)
        self.assertEqual(len(result["contacted_hosts"]), 1)

    def test_explicit_roots_are_seeded_without_external_frontier(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "automation" / "codegen" / "meta_state"
            state.mkdir(parents=True)
            (state / "network_policy_envelope.json").write_text(
                json.dumps(
                    {
                        "authorized_roots": ["root.example.test"],
                        "ttl_seconds": 3600,
                        "max_dynamic_hosts": 10,
                        "inherit_subdomains": True,
                    }
                ),
                encoding="utf-8",
            )
            (state / "discovery_policy.json").write_text("{}", encoding="utf-8")
            (state / "authority_reviewed_grants.json").write_text("{}", encoding="utf-8")
            (root / "senju" / "state").mkdir(parents=True)
            (root / "senju" / "state" / "standing_authorizations.json").write_text("{}", encoding="utf-8")
            seed = network_policy_seed.build_seed(state, root)
            self.assertEqual(seed["hosts"], ["root.example.test"])
            self.assertEqual(seed["urls"], ["https://root.example.test/"])


if __name__ == "__main__":
    unittest.main()
