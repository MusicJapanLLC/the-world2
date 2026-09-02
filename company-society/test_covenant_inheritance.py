from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "SKEPTIC": ROOT / "tomoki-agents/prompts/skeptic.md",
    "HOUND": ROOT / "tomoki-agents/prompts/hound.md",
    "FORGE": ROOT / "tomoki-agents/prompts/forge.md",
    "MANAGER": ROOT / "tomoki-agents/prompts/manager.md",
}
BOSS = ROOT / ".github/agents/ai-factory-boss.agent.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CovenantInheritanceTests(unittest.TestCase):
    def test_all_runtime_prompts_inherit_covenant(self):
        for role, path in PROMPTS.items():
            with self.subTest(role=role):
                text = read(path)
                lower = text.lower()
                self.assertIn("THE COVENANT", text)
                self.assertIn("company-society/FAITH.md", text)
                self.assertTrue("rest" in lower or "休息" in text, f"{role}: missing rest/sanctuary principle")
                self.assertTrue("autonomy" in lower or "自律" in text, f"{role}: missing autonomy principle")
                self.assertTrue("HELP -> WHO -> WHY -> SUCCESS" in text, f"{role}: missing mutual-aid contract")
                self.assertTrue("safety" in lower or "安全境界" in text, f"{role}: missing safety supremacy")

    def test_each_role_keeps_its_distinct_faith_duty(self):
        expected = {
            "SKEPTIC": "Truth before comfort",
            "HOUND": "Confession creates memory",
            "FORGE": "Improvement is worship",
            "MANAGER": "Repair before blame",
        }
        for role, duty in expected.items():
            with self.subTest(role=role):
                self.assertIn(duty, read(PROMPTS[role]))

    def test_boss_keeps_covenant_attention_boundary(self):
        text = read(BOSS)
        lower = text.lower()
        self.assertIn("THE COVENANT", text)
        self.assertIn("company-society/FAITH.md", text)
        self.assertTrue("休息" in text or "rest" in lower)
        self.assertTrue("相互扶助" in text or "peer-support" in lower)
        self.assertTrue("安全境界" in text or "safety" in lower)
        self.assertIn("CEO", text)
        self.assertIn("休息は失敗として報告しない", text)

    def test_autonomy_scripture_exists(self):
        text = read(ROOT / "company-society/AUTONOMY.md")
        for marker in ["SANCTUARY", "FELLOWSHIP", "PILGRIMAGE", "AUTONOMY LADDER"]:
            self.assertIn(marker, text)

    def test_mutual_aid_is_not_role_takeover(self):
        combined = "\n".join(read(path) for path in PROMPTS.values())
        self.assertTrue(
            "Never duplicate another active worker's task" in combined
            or "重複dispatchしない" in combined,
            "mutual aid must preserve ownership rather than create duplicate work",
        )


if __name__ == "__main__":
    unittest.main()
