from __future__ import annotations

import json

import pytest

from senju.lab_planner import (
    COVERAGE_THRESHOLD,
    MANIFEST_SCHEMA,
    MAX_HIT_COUNT,
    analyze_coverage,
    find_gaps,
    plan,
)
from senju.targets.base import VULN_CLASSES


def test_coverage_input_is_bounded_and_unknown_keys_are_ignored() -> None:
    first, second, third = list(VULN_CLASSES)[:3]
    coverage = analyze_coverage(
        {
            "vuln_class_hits": {
                first: -10,
                second: True,
                third: MAX_HIT_COUNT + 99,
                "not-a-real-class": 999,
            }
        }
    )
    assert coverage[first] == 0
    assert coverage[second] == 0
    assert coverage[third] == MAX_HIT_COUNT
    assert "not-a-real-class" not in coverage


def test_gap_order_is_stable_by_count_then_name() -> None:
    coverage = {vc: COVERAGE_THRESHOLD for vc in VULN_CLASSES}
    selected = sorted(list(VULN_CLASSES)[:3])
    coverage[selected[0]] = 1
    coverage[selected[1]] = 0
    coverage[selected[2]] = 1
    assert find_gaps(coverage) == [selected[1], selected[0], selected[2]]


def test_plan_is_idempotent_and_assigns_each_gap_once(tmp_path) -> None:
    summary = tmp_path / "summary.json"
    output = tmp_path / "labs"
    summary.write_text(json.dumps({"vuln_class_hits": {}}), encoding="utf-8")

    first = plan(summary, output, max_manifests=3)
    assert 1 <= len(first) <= 3

    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in first]
    assert all(item["schema"] == MANIFEST_SCHEMA for item in manifests)
    assert all(len(item["fingerprint"]) == 64 for item in manifests)

    flattened = [vc for item in manifests for vc in item["coverage_gaps"]]
    assert len(flattened) == len(set(flattened))
    assert set(flattened) == set(VULN_CLASSES)

    second = plan(summary, output, max_manifests=3)
    assert second == []


def test_full_coverage_produces_no_manifests(tmp_path) -> None:
    summary = tmp_path / "summary.json"
    output = tmp_path / "labs"
    summary.write_text(
        json.dumps(
            {"vuln_class_hits": {vc: COVERAGE_THRESHOLD for vc in VULN_CLASSES}}
        ),
        encoding="utf-8",
    )
    assert plan(summary, output, max_manifests=3) == []


def test_invalid_manifest_budget_is_rejected(tmp_path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        plan(summary, tmp_path / "labs", max_manifests=0)
    with pytest.raises(ValueError):
        plan(summary, tmp_path / "labs", max_manifests=999)


def test_non_object_summary_is_rejected(tmp_path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        plan(summary, tmp_path / "labs", max_manifests=3)
