"""Test suite for the generated fizzbuzz module."""
import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).parents[3] / "automation/codegen/generated/fizzbuzz.py"
    spec = importlib.util.spec_from_file_location("fizzbuzz", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fizzbuzz_basic():
    m = load_module()
    result = m.fizzbuzz(15)
    assert result[0] == "1"
    assert result[2] == "Fizz"
    assert result[4] == "Buzz"
    assert result[14] == "FizzBuzz"


def test_fizzbuzz_length():
    m = load_module()
    assert len(m.fizzbuzz(100)) == 100


def test_stats_counts():
    m = load_module()
    result = m.fizzbuzz(15)
    s = m.stats(result)
    assert s["fizzbuzz"] == 1   # 15
    assert s["fizz"] == 4       # 3,6,9,12
    assert s["buzz"] == 2       # 5,10
    assert s["number"] == 8


def test_stats_keys():
    m = load_module()
    s = m.stats(m.fizzbuzz(1))
    assert set(s.keys()) == {"fizz", "buzz", "fizzbuzz", "number"}
