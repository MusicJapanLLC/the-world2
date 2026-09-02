import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import child_memory as cm
import playground_engine as pe


class ChildMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(Path("company-society/child_guild.json").read_text(encoding="utf-8"))

    def test_fresh_memory_schema(self):
        memory = cm.fresh()
        self.assertEqual("child-guild-memory/v1", memory["schema"])
        self.assertEqual([], memory["episodes"])

    def test_record_episode_changes_selection_pressure(self):
        memory = cm.fresh()
        first = pe.build(self.registry, "same-seed", memory)
        cm.record_episode(memory, first)
        second = pe.build(self.registry, "same-seed", memory)
        self.assertNotEqual(first["child"]["id"], second["child"]["id"])
        self.assertNotEqual(first["action"]["kind"], second["action"]["kind"])
        self.assertNotEqual(first["child"]["adventure"], second["child"]["adventure"])

    def test_ingest_observation_extracts_concepts_without_secret_fields(self):
        memory = cm.fresh()
        cm.ingest_observation(memory, {
            "summary": "Robotics simulation found a surprising latency pattern in rendering pipeline",
            "api_key": "sk-super-secret-value",
            "token": "ghp_secret-token",
        }, "unit-test")
        concepts = set(memory["concept_counts"])
        self.assertIn("robotics", concepts)
        self.assertIn("simulation", concepts)
        self.assertNotIn("secret", concepts)
        self.assertNotIn("super", concepts)

    def test_duplicate_observation_is_deduped(self):
        memory = cm.fresh()
        payload = {"summary": "same observation about adaptive planning"}
        cm.ingest_observation(memory, payload, "one")
        before = dict(memory["concept_counts"])
        cm.ingest_observation(memory, payload, "two")
        self.assertEqual(before, memory["concept_counts"])
        self.assertEqual(1, len(memory["observation_digests"]))

    def test_fleet_compaction_drops_raw_results_and_keeps_learning(self):
        fleet = {
            "schema": "child-external-fleet/v1",
            "fleet_size": 50,
            "mode": "public-read-only-open-domain-discovery",
            "results": [{"url": "https://example.com/secret-looking-path", "snippet": "raw html body"}],
            "summary": {
                "status_counts": {"fetched": 48, "http_blocked": 2},
                "distinct_domains": 31,
                "top_concepts": ["robotics", "agents", "memory"],
                "research_hypotheses": ["Test whether memory changes learning assumptions."],
            },
            "rnd_capsule": {
                "top_concepts": ["robotics", "agents"],
                "hypotheses": ["Try a bounded learning lens."],
            },
        }
        compact = cm.compact_fleet_observation(fleet)
        self.assertNotIn("results", compact)
        self.assertNotIn("url", json.dumps(compact).lower())
        memory = cm.fresh()
        cm.ingest_observation(memory, compact, "child-external-fleet")
        self.assertIn("robotics", memory["concept_counts"])

    def test_round_trip_file(self):
        memory = cm.fresh()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.json"
            cm.save(memory, path)
            loaded = cm.load(path)
            self.assertEqual(cm.SCHEMA, loaded["schema"])


if __name__ == "__main__":
    unittest.main()
