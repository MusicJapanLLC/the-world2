"""Tests for Senju Autonomy Core (Queue, Prioritization, Deduplication, and Closed Loop)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from senju.autonomy.engine import AutonomyEngine, run_autonomy_cycle
from senju.autonomy.queue import AutonomyQueue, WorkItem, WorkItemStatus
from senju.external import BUILTIN_AUTHORITY_SCOPES, ExternalAuthorityScope, ExternalContactPolicy
from senju.targets.base import ARCHETYPES, VULN_CLASSES


def test_work_item_deduplication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        q = AutonomyQueue(Path(tmp) / "queue.json")
        item1 = WorkItem(
            item_id="item-1",
            hypothesis="Test hypothesis A",
            category="combat_tactics",
            expected_value=0.8,
            parameters={"pop": 20},
        )
        item2 = WorkItem(
            item_id="item-2",
            hypothesis="Test hypothesis A",
            category="combat_tactics",
            expected_value=0.8,
            parameters={"pop": 20},
        )
        assert q.enqueue(item1) is True
        assert q.enqueue(item2) is False  # Duplicate rejected


def test_deterministic_prioritization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        q = AutonomyQueue(Path(tmp) / "queue.json")
        low_val = WorkItem(
            item_id="low",
            hypothesis="Low value",
            category="test",
            expected_value=0.2,
            cost_budget_matches=500,
        )
        high_val = WorkItem(
            item_id="high",
            hypothesis="High value",
            category="test",
            expected_value=0.9,
            cost_budget_matches=200,
        )
        q.enqueue(low_val)
        q.enqueue(high_val)

        selected = q.select_next()
        assert selected is not None
        assert selected.item_id == "high"


def test_autonomy_engine_closed_loop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results = run_autonomy_cycle(state_dir=tmp, max_cycles=1)
        assert len(results) == 1
        res = results[0]
        assert res.status == WorkItemStatus.COMPLETED.value
        assert res.matches_run > 0
        assert Path(res.report_path).exists()


def test_ai_agent_vulnerability_classes_present() -> None:
    assert "prompt_injection" in VULN_CLASSES
    assert "tool_misuse" in VULN_CLASSES
    assert "agent_priv_esc" in VULN_CLASSES
    assert "ai_agent_cluster" in ARCHETYPES


def test_external_authority_scopes() -> None:
    assert "threat_intel_public" in BUILTIN_AUTHORITY_SCOPES
    scope = BUILTIN_AUTHORITY_SCOPES["threat_intel_public"]
    policy = scope.to_policy()
    assert "services.nvd.nist.gov" in policy.allow_hosts
    assert policy.allow_http is False
