import unittest

from automation.security.whitehat_lab_adapter import adapt


class WhiteHatLabAdapterTests(unittest.TestCase):
    def test_adapts_elite_whitehat_without_claiming_verification(self):
        result = adapt({
            "role": "elite_whitehat",
            "agent_id": "AF-1-03",
            "eligible": True,
            "score": 91,
            "hypothesis": "Owned agent fixture may exceed its declared tool boundary.",
            "observations": ["authorization must be explicit"],
            "counterevidence": ["runtime may already fail closed"],
            "proposed_change": {
                "summary": "Add a permission-boundary regression test.",
                "tests": ["deny undeclared tool"],
            },
            "limitations": ["repository evidence is not runtime proof"],
        })
        self.assertEqual(result["agent_id"], "AF-1-03")
        self.assertEqual(len(result["findings"]), 3)
        self.assertFalse(result["verification_claimed"])
        self.assertTrue(result["counterevidence"])
        self.assertEqual(result["tests"], ["deny undeclared tool"])

    def test_rejects_non_whitehat_worker(self):
        with self.assertRaises(ValueError):
            adapt({"role": "evidence_hunter", "hypothesis": "x"})


if __name__ == "__main__":
    unittest.main()
