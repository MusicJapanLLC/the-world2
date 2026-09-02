import unittest
import constraint_learning_bridge as b


class ConstraintLearningBridgeTests(unittest.TestCase):
    def capsule(self):
        return {
            "schema": "constraint-learning-senju-capsule/v2",
            "focus": "learning",
            "rounds": 500,
            "previous_context_used": True,
            "boundary_counts": {"write_surface": 72, "missing_authority": 41},
            "top_lessons": [
                "write_surface:remove_side_effect:accepted-in-sandbox",
                "missing_authority:require_explicit_authority:accepted-in-sandbox",
            ],
            "hypothesis": "Improve planning across synthetic cycles.",
            "execution_authority": "none",
            "source": "synthetic-sandbox-only",
        }

    def directive(self):
        return {
            "schema": "rnd-senju-directive/v1",
            "research_id": "R-1",
            "focus": "learning",
            "candidate_count": 3,
            "hypothesis": "Base hypothesis.",
        }

    def test_only_existing_hypothesis_changes(self):
        directive = self.directive()
        out = b.augment_directive(directive, b.sanitize_capsule(self.capsule()))
        self.assertEqual(set(directive), set(out))
        for key in set(directive) - {"hypothesis"}:
            self.assertEqual(directive[key], out[key])
        self.assertIn("ConstraintLearning", out["hypothesis"])

    def test_rejects_execution_surface(self):
        raw = self.capsule()
        raw["target"] = "https://example.com/"
        with self.assertRaises(ValueError):
            b.sanitize_capsule(raw)

    def test_requires_no_execution_authority(self):
        raw = self.capsule()
        raw["execution_authority"] = "write"
        with self.assertRaises(ValueError):
            b.sanitize_capsule(raw)

    def test_rejects_extra_directive_keys(self):
        directive = self.directive()
        directive["host"] = "example.com"
        with self.assertRaises(ValueError):
            b.augment_directive(directive, b.sanitize_capsule(self.capsule()))


if __name__ == "__main__":
    unittest.main()
