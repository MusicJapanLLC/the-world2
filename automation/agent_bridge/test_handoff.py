#!/usr/bin/env python3
"""Tests for Autonomous Agent-to-Agent Engineering Handoff Bridge."""
from __future__ import annotations

import pytest
from typing import Any

from automation.agent_bridge.handoff import (
    AGENT_CLAUDE_HUMAN,
    AGENT_FOUNDRY,
    AGENT_JULES,
    AGENT_OPENHANDS,
    AGENT_SENJU_RND,
    AGENT_THE_WORLD,
    STATUS_ACCEPTED,
    STATUS_EXTENDED,
    STATUS_REJECTED_DUPLICATE,
    STATUS_REJECTED_QUEUE_FULL,
    STATUS_REJECTED_STALE,
    AgentHandoffContract,
    HandoffQueue,
    build_evidence_pack,
    decide_next_agent,
    is_duplicate,
    run_engineering_loop,
    validate_freshness,
)


def test_contract_serialization_and_validation() -> None:
    contract = AgentHandoffContract(
        objective="Fix build script error",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_FOUNDRY,
        base_sha="sha_100",
        head_sha="sha_101",
        affected_subsystems=["automation/ai_foundry"],
        affected_files=["automation/ai_foundry/engineering_loop.py"],
        evidence_refs={"logs": "Exit status 1 in test step"},
        blocker={"type": "build_failure", "description": "Syntax error in build command"},
        acceptance_condition="build passes cleanly",
    )

    data = contract.to_dict()
    assert data["source_agent"] == AGENT_JULES
    assert data["recommended_next_agent"] == AGENT_FOUNDRY
    assert data["handoff_id"] != ""

    deserialized = AgentHandoffContract.from_dict(data)
    assert deserialized.objective == contract.objective
    assert deserialized.handoff_id == contract.handoff_id


def test_invalid_agent_raises_error() -> None:
    with pytest.raises(ValueError, match="Invalid source_agent"):
        AgentHandoffContract(
            objective="test",
            source_agent="UNKNOWN_BOT",
            recommended_next_agent=AGENT_JULES,
            base_sha="sha_1",
            head_sha="sha_2",
        )


def test_deterministic_next_agent_routing() -> None:
    # 1. Architecture / Policy -> CLAUDE_HUMAN
    r_claude = decide_next_agent(
        blocker={"type": "architecture", "description": "Requires core design approval"},
    )
    assert r_claude == AGENT_CLAUDE_HUMAN

    # 2. Investigation / Unknown root cause -> OPENHANDS
    r_openhands = decide_next_agent(
        blocker={"type": "unknown_root_cause", "description": "Need deep trace analysis"},
        evidence={"requires_investigation": True},
    )
    assert r_openhands == AGENT_OPENHANDS

    # 3. Build / Deploy -> FOUNDRY
    r_foundry = decide_next_agent(
        blocker={"type": "build_failure", "description": "Docker container failed to build"},
        affected_subsystems=["automation/ai_foundry"],
    )
    assert r_foundry == AGENT_FOUNDRY

    # 4. Runtime / Autonomy -> THE_WORLD
    r_world = decide_next_agent(
        blocker={"type": "autonomy_loop", "description": "Realtime kernel timeout"},
        affected_subsystems=["automation/world"],
    )
    assert r_world == AGENT_THE_WORLD

    # 5. Experiment / R&D -> SENJU_RND
    r_senju = decide_next_agent(
        blocker={"type": "experiment", "description": "Evaluate model hypothesis"},
        affected_subsystems=["senju"],
    )
    assert r_senju == AGENT_SENJU_RND

    # 6. Scoped code repair (default) -> JULES
    r_jules = decide_next_agent(
        blocker={"type": "bug_fix", "description": "Off-by-one error in parser"},
        affected_subsystems=["src"],
    )
    assert r_jules == AGENT_JULES


def test_stale_sha_rejection() -> None:
    contract = AgentHandoffContract(
        objective="Repair component",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_old_100",
        head_sha="sha_old_101",
    )

    # Fresh matching current head SHA
    is_fresh, _ = validate_freshness(contract, "sha_old_101")
    assert is_fresh is True

    # Fresh matching current base SHA
    is_fresh_base, _ = validate_freshness(contract, "sha_old_100")
    assert is_fresh_base is True

    # Stale SHA rejection
    is_fresh_stale, reason = validate_freshness(contract, "sha_new_999")
    assert is_fresh_stale is False
    assert "Stale handoff" in reason


def test_deduplication() -> None:
    h1 = AgentHandoffContract(
        objective="Refactor auth loop",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_1",
        head_sha="sha_2",
        affected_subsystems=["security"],
        status=STATUS_ACCEPTED,
    )

    h2 = AgentHandoffContract(
        objective="Refactor auth loop",
        source_agent=AGENT_SENJU_RND,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_1",
        head_sha="sha_2",
        affected_subsystems=["security"],
        status=STATUS_ACCEPTED,
    )

    assert is_duplicate(h2, [h1]) is True

    h3 = AgentHandoffContract(
        objective="Refactor database schema",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_1",
        head_sha="sha_2",
        affected_subsystems=["security"],
    )
    assert is_duplicate(h3, [h1]) is False


def test_extending_active_work_over_overlapping_branches() -> None:
    queue = HandoffQueue(max_size=5)

    h1 = AgentHandoffContract(
        objective="Fix parser bug",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_FOUNDRY,
        base_sha="sha_100",
        head_sha="sha_100",
        affected_subsystems=["automation/ai_foundry"],
        affected_files=["automation/ai_foundry/parser.py"],
    )
    res1 = queue.process_handoff(h1, "sha_100")
    assert res1.status == STATUS_ACCEPTED

    h2 = AgentHandoffContract(
        objective="Add parser unit tests",
        source_agent=AGENT_OPENHANDS,
        recommended_next_agent=AGENT_FOUNDRY,
        base_sha="sha_100",
        head_sha="sha_101",
        affected_subsystems=["automation/ai_foundry"],
        affected_files=["automation/ai_foundry/test_parser.py"],
    )
    res2 = queue.process_handoff(h2, "sha_101")

    assert res2.status == STATUS_EXTENDED
    # The active work in queue was extended rather than starting an overlapping branch
    active = queue.get_active()[0]
    assert "Add parser unit tests" in active.objective
    assert "automation/ai_foundry/test_parser.py" in active.affected_files


def test_bounded_queue_and_concurrency_limits() -> None:
    queue = HandoffQueue(max_size=2, max_concurrency_per_agent=1)

    h1 = AgentHandoffContract(
        objective="Task 1",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_100",
        head_sha="sha_100",
        affected_subsystems=["sub1"],
    )
    res1 = queue.process_handoff(h1, "sha_100")
    assert res1.status == STATUS_ACCEPTED

    # Second handoff for same recommended agent exceeds max_concurrency_per_agent=1
    h2 = AgentHandoffContract(
        objective="Task 2",
        source_agent=AGENT_JULES,
        recommended_next_agent=AGENT_OPENHANDS,
        base_sha="sha_100",
        head_sha="sha_100",
        affected_subsystems=["sub2"],
    )
    res2 = queue.process_handoff(h2, "sha_100")
    assert res2.status == STATUS_REJECTED_QUEUE_FULL
    assert "Concurrency limit reached" in res2.evidence_refs["rejection_reason"]


def test_evidence_pack_generation() -> None:
    contract = AgentHandoffContract(
        objective="Deploy build artifact",
        source_agent=AGENT_FOUNDRY,
        recommended_next_agent=AGENT_CLAUDE_HUMAN,
        base_sha="sha_100",
        head_sha="sha_102",
        affected_subsystems=["ci"],
        affected_files=["deploy.sh"],
        evidence_refs={"test_outcomes": "10 passed", "run_id": "run_99"},
        blocker={"description": "Final merge decision required"},
        acceptance_condition="Human approval",
        resulting_artifact_ref="pr_777",
    )

    pack = build_evidence_pack(contract)
    assert pack["schema"] == "agent-handoff-evidence-pack/v1"
    assert pack["transition"] == "FOUNDRY -> CLAUDE_HUMAN"
    assert pack["commit_context"]["head_sha"] == "sha_102"
    assert pack["evidence_summary"]["test_outcomes"] == "10 passed"
    assert pack["resulting_artifact_ref"] == "pr_777"


def test_synthetic_end_to_end_multi_agent_handoff_loop() -> None:
    """Demonstrates synthetic multi-agent handoff engineering loop.

    Sequence:
    1. JULES detects build failure -> routes/hands off to FOUNDRY
    2. FOUNDRY fixes build -> routes/hands off to SENJU_RND for hypothesis experiment
    3. SENJU_RND verifies experiment -> hands off to CLAUDE_HUMAN for final merge judgment
    """

    def mock_action_handler(agent: str, state: dict[str, Any]) -> dict[str, Any]:
        if agent == AGENT_FOUNDRY:
            return {
                "verified": True,
                "output": "Build pipeline repaired cleanly",
                "head_sha": "sha_step_1",
                "next_owner": AGENT_SENJU_RND,
                "artifact_ref": "foundry_build_job_101",
                "blocker": {"type": "experiment", "description": "Need scenario evaluation"},
            }
        elif agent == AGENT_SENJU_RND:
            return {
                "verified": True,
                "output": "R&D experiment scenario passed",
                "head_sha": "sha_step_2",
                "next_owner": AGENT_CLAUDE_HUMAN,
                "artifact_ref": "senju_report_202",
                "blocker": {"type": "architecture", "description": "Human review & merge approval required"},
            }
        elif agent == AGENT_CLAUDE_HUMAN:
            return {
                "verified": True,
                "output": "PR approved and merged",
                "head_sha": "sha_step_3",
                "next_owner": AGENT_CLAUDE_HUMAN,
                "artifact_ref": "pr_merged_303",
            }
        return {
            "verified": False,
            "output": "Unrecognized action",
        }

    initial_state = {
        "objective": "Build and evaluate security experiment",
        "current_agent": AGENT_JULES,
        "affected_subsystems": ["automation/ai_foundry"],
        "affected_files": ["automation/ai_foundry/engineering_loop.py"],
        "base_sha": "sha_step_0",
        "blocker": {"type": "build_failure", "description": "Compilation failed in CI"},
    }

    history = run_engineering_loop(
        initial_state=initial_state,
        current_repo_sha="sha_step_0",
        action_handler=mock_action_handler,
        max_steps=5,
    )

    assert len(history) == 2
    # Step 0: JULES -> FOUNDRY
    assert history[0]["decided_owner"] == AGENT_FOUNDRY
    assert history[0]["handoff"]["status"] in {STATUS_ACCEPTED, STATUS_EXTENDED}
    assert history[0]["evidence_pack"]["transition"] == "FOUNDRY -> SENJU_RND"

    # Step 1: SENJU_RND -> CLAUDE_HUMAN
    assert history[1]["decided_owner"] == AGENT_SENJU_RND
    assert history[1]["evidence_pack"]["transition"] == "SENJU_RND -> CLAUDE_HUMAN"
