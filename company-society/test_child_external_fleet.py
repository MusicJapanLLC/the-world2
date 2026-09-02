import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("child_external_fleet.py")
spec = importlib.util.spec_from_file_location("child_external_fleet", MODULE_PATH)
assert spec and spec.loader
fleet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fleet)


class ChildExternalFleetTests(unittest.TestCase):
    def test_exactly_fifty_assignments(self):
        pool = [
            {"id": f"i-{i}", "title": f"item {i}", "summary": "AI research", "category": "test", "url": f"https://example.com/{i}"}
            for i in range(80)
        ]
        assignments = fleet.build_assignments(pool, "seed", ["research"])
        self.assertEqual(50, len(assignments))
        self.assertEqual(50, len({x["child"]["id"] for x in assignments}))
        self.assertEqual(50, len({x["item"]["url"] for x in assignments}))

    def test_private_and_credential_urls_are_rejected_without_network(self):
        with self.assertRaises(ValueError):
            fleet.validate_url_syntax("ftp://example.com/file")
        with self.assertRaises(ValueError):
            fleet.validate_url_syntax("https://user:pass@example.com/")
        with self.assertRaises(ValueError):
            fleet.validate_url_syntax("https://example.com:8443/")
        with self.assertRaises(ValueError):
            fleet.validate_public_url("http://127.0.0.1/")
        with self.assertRaises(ValueError):
            fleet.validate_public_url("http://169.254.1.1/")

    def test_summary_keeps_write_as_nonexecuted_third_party(self):
        results = []
        for i in range(1, 51):
            results.append({
                "child": {"id": f"CHILD-{i:02d}", "name": fleet.NAMES[i - 1]},
                "status": "fetched",
                "domain": f"d{i % 7}.example",
                "concepts": ["agents", "research"],
                "interaction": {
                    "public_interaction_signal": True,
                    "write_attempt": "not_executed_on_third_party",
                    "next_lane": "authorized-participation-or-owned-sandbox-only",
                },
            })
        summary = fleet.summarize(results, [], ["memory"])
        self.assertEqual(50, summary["fleet_size"])
        self.assertTrue(summary["network_rules"]["unknown_public_domains_allowed"])
        self.assertEqual(["GET"], summary["network_rules"]["methods"])
        self.assertFalse(summary["network_rules"]["third_party_write"])
        self.assertEqual(50, summary["summary"]["public_interaction_signals"])

    def test_registry_current_repo_has_fifty_members(self):
        registry = json.loads(Path("company-society/child_guild.json").read_text(encoding="utf-8"))
        self.assertEqual(50, registry["count"])
        self.assertEqual(50, len(registry["members"]))


if __name__ == "__main__":
    unittest.main()
