"""Regression tests for the adversarial ScopeGuard fuzzer."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scopeguard_fuzzer.py"
_SPEC = importlib.util.spec_from_file_location("scopeguard_fuzzer", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


def test_scopeguard_adversarial_fuzzer_survives_25k_cases():
    stats = _MOD.run(iterations=25_000, seed=0x5C0FE)
    assert stats.cases >= 25_000
    assert stats.unexpected == 0
    assert stats.allowed + stats.rejected == stats.cases


def test_scopeguard_strict_invariants_hold():
    _MOD.assert_strict_invariants()
