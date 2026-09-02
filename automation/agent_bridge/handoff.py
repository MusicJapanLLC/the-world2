#!/usr/bin/env python3
"""Autonomous Agent-to-Agent Engineering Handoff Bridge.

Implements machine-readable handoff contracts, deterministic next-agent routing,
stale SHA rejection, deduplication, active work extension, bounded queue limits,
concise evidence pack generation, and the OBSERVE -> DECIDE OWNER -> ACT -> VERIFY -> HANDOFF -> NEXT ACTION loop.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

# Standard Agent Identifiers
AGENT_OPENHANDS = "OPENHANDS"
AGENT_JULES = "JULES"
AGENT_SENJU_RND = "SENJU_RND"
AGENT_FOUNDRY = "FOUNDRY"
AGENT_THE_WORLD = "THE_WORLD"
AGENT_CLAUDE_HUMAN = "CLAUDE_HUMAN"

VALID_AGENTS = {
    AGENT_OPENHANDS,
    AGENT_JULES,
    AGENT_SENJU_RND,
    AGENT_FOUNDRY,
    AGENT_THE_WORLD,
    AGENT_CLAUDE_HUMAN,
}

# Overlap relationships
OVERLAP_ADDITIVE = "additive"
OVERLAP_REPLACEMENT = "replacement"
OVERLAP_TRANSPLANT = "transplant"
OVERLAP_SUPERSEDES = "supersedes"

VALID_OVERLAPS = {
    OVERLAP_ADDITIVE,
    OVERLAP_REPLACEMENT,
    OVERLAP_TRANSPLANT,
    OVERLAP_SUPERSEDES,
}

# Handoff Statuses
STATUS_PENDING = "PENDING"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_EXTENDED = "EXTENDED"
STATUS_REJECTED_STALE = "REJECTED_STALE"
STATUS_REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
STATUS_REJECTED_QUEUE_FULL = "REJECTED_QUEUE_FULL"
STATUS_COMPLETED = "COMPLETED"


@dataclass
class AgentHandoffContract:
    objective: str
    source_agent: str
    recommended_next_agent: str
    base_sha: str
    head_sha: str
    affected_subsystems: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    evidence_refs: dict[str, Any] = field(default_factory=dict)
    blocker: dict[str, Any] | str = field(default_factory=dict)
    overlap_relationship: str = OVERLAP_ADDITIVE
    acceptance_condition: str = ""
    resulting_artifact_ref: str = ""
    status: str = STATUS_PENDING
    handoff_id: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.source_agent not in VALID_AGENTS:
            raise ValueError(f"Invalid source_agent: {self.source_agent}")
        if self.recommended_next_agent not in VALID_AGENTS:
            raise ValueError(f"Invalid recommended_next_agent: {self.recommended_next_agent}")
        if self.overlap_relationship not in VALID_OVERLAPS:
            raise ValueError(f"Invalid overlap_relationship: {self.overlap_relationship}")

        if not self.handoff_id:
            raw = f"{self.objective}:{self.source_agent}:{self.recommended_next_agent}:{self.base_sha}:{self.head_sha}"
            self.handoff_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentHandoffContract:
        cleaned = dict(data)
        return cls(**cleaned)


def decide_next_agent(
    evidence: dict[str, Any] | None = None,
    blocker: dict[str, Any] | str | None = None,
    affected_subsystems: list[str] | None = None,
    task_type: str = "",
) -> str:
    """Deterministically route to the next agent based on evidence and blocker classification."""
    ev = evidence or {}
    subsystems = [s.lower() for s in (affected_subsystems or [])]
    task = task_type.lower()

    blocker_str = ""
    blocker_type = ""
    if isinstance(blocker, dict):
        blocker_str = str(blocker.get("description") or blocker.get("reason") or "").lower()
        blocker_type = str(blocker.get("type") or blocker.get("category") or "").lower()
    elif isinstance(blocker, str):
        blocker_str = blocker.lower()

    # Priority 1: Architectural / Merge / Policy judgment -> CLAUDE_HUMAN
    if (
        blocker_type in {"architecture", "policy", "merge_conflict", "human_approval"}
        or "architecture" in blocker_str
        or "merge" in blocker_str
        or "policy" in blocker_str
        or "human judgment" in blocker_str
        or task == "architectural_review"
    ):
        return AGENT_CLAUDE_HUMAN

    # Priority 2: Root cause investigation / deep code review -> OPENHANDS
    if (
        blocker_type in {"investigation", "unknown_root_cause", "code_review"}
        or "root cause" in blocker_str
        or "investigate" in blocker_str
        or "review" in blocker_str
        or ev.get("requires_investigation")
        or task == "investigation"
    ):
        return AGENT_OPENHANDS

    # Priority 3: Experiment-driven engineering / R&D hypothesis -> SENJU_RND
    if (
        blocker_type in {"experiment", "hypothesis", "rnd_scenario"}
        or "experiment" in blocker_str
        or "hypothesis" in blocker_str
        or "scenario" in blocker_str
        or task == "experiment"
    ):
        return AGENT_SENJU_RND

    # Priority 4: CI / Build / Deploy pipeline work -> FOUNDRY
    if (
        blocker_type in {"build_failure", "deploy_pipeline", "ci_error"}
        or "build" in blocker_str
        or "deploy" in blocker_str
        or "pipeline" in blocker_str
        or "docker" in blocker_str
        or any(s in {"automation/ai_foundry", "ci", "deploy"} for s in subsystems)
        or task == "build_deploy"
    ):
        return AGENT_FOUNDRY

    # Priority 5: Runtime / Autonomy orchestration -> THE_WORLD
    if (
        blocker_type in {"runtime_orchestration", "autonomy_loop"}
        or "runtime" in blocker_str
        or "orchestration" in blocker_str
        or "external presence" in blocker_str
        or any(s in {"automation/world", "outside-world", "runtime"} for s in subsystems)
        or task == "runtime_autonomy"
    ):
        return AGENT_THE_WORLD

    # Priority 6: Default targeted code repair / bug fix -> JULES
    return AGENT_JULES


def validate_freshness(handoff: AgentHandoffContract | dict[str, Any], current_repo_sha: str) -> tuple[bool, str]:
    """Reject stale handoffs when current repository SHA does not match expected SHA context."""
    data = handoff.to_dict() if isinstance(handoff, AgentHandoffContract) else handoff
    base_sha = str(data.get("base_sha") or "")
    head_sha = str(data.get("head_sha") or "")
    current = str(current_repo_sha or "").strip()

    if not current:
        return False, "Current repository SHA is empty"

    # Head SHA or Base SHA must match current repository SHA context
    if current != head_sha and current != base_sha:
        return False, f"Stale handoff: current SHA ({current}) matches neither base_sha ({base_sha}) nor head_sha ({head_sha})"

    return True, "Fresh SHA context"


def is_duplicate(
    handoff: AgentHandoffContract | dict[str, Any],
    existing_handoffs: list[AgentHandoffContract | dict[str, Any]],
) -> bool:
    """Check whether a handoff is equivalent to an active handoff in queue."""
    target = handoff.to_dict() if isinstance(handoff, AgentHandoffContract) else handoff
    target_obj = str(target.get("objective") or "").strip().lower()
    target_subsystems = set(target.get("affected_subsystems") or [])
    target_next = target.get("recommended_next_agent")

    for item in existing_handoffs:
        existing = item.to_dict() if isinstance(item, AgentHandoffContract) else item
        if existing.get("status") in {STATUS_REJECTED_STALE, STATUS_REJECTED_DUPLICATE, STATUS_COMPLETED}:
            continue

        ex_obj = str(existing.get("objective") or "").strip().lower()
        ex_subsystems = set(existing.get("affected_subsystems") or [])
        ex_next = existing.get("recommended_next_agent")

        if target_obj == ex_obj and target_next == ex_next and target_subsystems == ex_subsystems:
            return True

    return False


def build_evidence_pack(handoff: AgentHandoffContract | dict[str, Any]) -> dict[str, Any]:
    """Produce a concise evidence pack consumable by the next agent without bloat."""
    data = handoff.to_dict() if isinstance(handoff, AgentHandoffContract) else handoff
    ev = data.get("evidence_refs") or {}
    blocker = data.get("blocker") or {}

    blocker_summary = blocker.get("description") if isinstance(blocker, dict) else str(blocker)

    return {
        "schema": "agent-handoff-evidence-pack/v1",
        "handoff_id": data.get("handoff_id"),
        "transition": f"{data.get('source_agent')} -> {data.get('recommended_next_agent')}",
        "objective": data.get("objective"),
        "commit_context": {"base_sha": data.get("base_sha"), "head_sha": data.get("head_sha")},
        "affected_subsystems": data.get("affected_subsystems"),
        "affected_files": data.get("affected_files"),
        "blocker_summary": blocker_summary,
        "evidence_summary": {
            "test_outcomes": ev.get("test_outcomes") or ev.get("tests"),
            "run_ref": ev.get("run_ref") or ev.get("run_id"),
            "logs_excerpt": (str(ev.get("logs") or "")[:500] if ev.get("logs") else ""),
        },
        "overlap_relationship": data.get("overlap_relationship"),
        "acceptance_condition": data.get("acceptance_condition"),
        "resulting_artifact_ref": data.get("resulting_artifact_ref"),
    }


class HandoffQueue:
    """Bounded queue manager enforcing concurrency limits, deduplication, and active work extension."""

    def __init__(self, max_size: int = 10, max_concurrency_per_agent: int = 3) -> None:
        self.max_size = max_size
        self.max_concurrency_per_agent = max_concurrency_per_agent
        self.queue: list[AgentHandoffContract] = []

    def get_active(self) -> list[AgentHandoffContract]:
        return [h for h in self.queue if h.status in {STATUS_PENDING, STATUS_ACCEPTED, STATUS_EXTENDED}]

    def process_handoff(
        self,
        handoff: AgentHandoffContract,
        current_repo_sha: str,
    ) -> AgentHandoffContract:
        # 1. Freshness check
        is_fresh, reason = validate_freshness(handoff, current_repo_sha)
        if not is_fresh:
            handoff.status = STATUS_REJECTED_STALE
            handoff.evidence_refs["rejection_reason"] = reason
            return handoff

        # 2. Deduplication check
        if is_duplicate(handoff, self.get_active()):
            handoff.status = STATUS_REJECTED_DUPLICATE
            handoff.evidence_refs["rejection_reason"] = "Equivalent active handoff exists in queue"
            return handoff

        # 3. Check if active work can be extended rather than starting overlapping branches
        active_items = self.get_active()
        for active in active_items:
            if (
                active.recommended_next_agent == handoff.recommended_next_agent
                and set(active.affected_subsystems).intersection(set(handoff.affected_subsystems))
            ):
                # Extend existing active work
                active.objective = f"{active.objective} + [Extended: {handoff.objective}]"
                active.affected_files = sorted(list(set(active.affected_files + handoff.affected_files)))
                active.evidence_refs[f"extended_from_{handoff.handoff_id}"] = handoff.evidence_refs
                active.head_sha = handoff.head_sha
                active.status = STATUS_EXTENDED

                handoff.status = STATUS_EXTENDED
                handoff.resulting_artifact_ref = f"extended_active_{active.handoff_id}"
                return handoff

        # 4. Check bounded queue capacity limits
        active_count = len(active_items)
        if active_count >= self.max_size:
            handoff.status = STATUS_REJECTED_QUEUE_FULL
            handoff.evidence_refs["rejection_reason"] = f"Queue size limit reached ({self.max_size})"
            return handoff

        agent_active_count = sum(1 for h in active_items if h.recommended_next_agent == handoff.recommended_next_agent)
        if agent_active_count >= self.max_concurrency_per_agent:
            handoff.status = STATUS_REJECTED_QUEUE_FULL
            handoff.evidence_refs["rejection_reason"] = (
                f"Concurrency limit reached for agent {handoff.recommended_next_agent} ({self.max_concurrency_per_agent})"
            )
            return handoff

        # Accepted
        handoff.status = STATUS_ACCEPTED
        self.queue.append(handoff)
        return handoff


def run_engineering_loop(
    initial_state: dict[str, Any],
    current_repo_sha: str,
    action_handler: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_steps: int = 5,
) -> list[dict[str, Any]]:
    """Executes the engineering loop: OBSERVE -> DECIDE OWNER -> ACT -> VERIFY -> HANDOFF -> NEXT ACTION.

    Demonstrates synthetic multi-agent handoff progressions.
    """
    queue = HandoffQueue()
    history = []
    state = dict(initial_state)
    active_sha = current_repo_sha

    for step in range(max_steps):
        # 1. OBSERVE
        subsystems = state.get("affected_subsystems") or []
        evidence = state.get("evidence") or {}
        blocker = state.get("blocker") or {}
        current_agent = state.get("current_agent", AGENT_JULES)

        # 2. DECIDE OWNER
        next_agent = decide_next_agent(
            evidence=evidence,
            blocker=blocker,
            affected_subsystems=subsystems,
            task_type=state.get("task_type", ""),
        )

        # 3. ACT
        action_result = action_handler(next_agent, state)

        # 4. VERIFY
        verified = bool(action_result.get("verified"))
        verification_details = action_result.get("details", "")

        # 5. HANDOFF
        next_owner = action_result.get("next_owner") or (AGENT_CLAUDE_HUMAN if verified else next_agent)
        step_head_sha = action_result.get("head_sha", active_sha)
        handoff = AgentHandoffContract(
            objective=state.get("objective", "Multi-agent task completion"),
            source_agent=next_agent,
            recommended_next_agent=next_owner,
            base_sha=state.get("base_sha", active_sha),
            head_sha=step_head_sha,
            affected_subsystems=subsystems,
            affected_files=state.get("affected_files", []),
            evidence_refs={
                "verification": verified,
                "details": verification_details,
                "action_output": action_result.get("output"),
            },
            blocker=action_result.get("blocker") or ({} if verified else blocker),
            overlap_relationship=action_result.get("overlap_relationship", OVERLAP_ADDITIVE),
            acceptance_condition=state.get("acceptance_condition", "Tests pass and output verified"),
            resulting_artifact_ref=action_result.get("artifact_ref", f"step_{step}_result"),
        )

        processed = queue.process_handoff(handoff, active_sha)
        evidence_pack = build_evidence_pack(processed)

        step_record = {
            "step": step,
            "phase": "COMPLETED",
            "observed_agent": current_agent,
            "decided_owner": next_agent,
            "action_result": action_result,
            "verified": verified,
            "handoff": processed.to_dict(),
            "evidence_pack": evidence_pack,
        }
        history.append(step_record)

        # 6. NEXT ACTION
        if verified and processed.recommended_next_agent == AGENT_CLAUDE_HUMAN:
            # Reached terminal completion / human architectural merge step
            break

        # Update state for next step
        state["current_agent"] = processed.recommended_next_agent
        state["evidence"] = processed.evidence_refs
        state["blocker"] = action_result.get("blocker") or ({} if verified else blocker)
        state["base_sha"] = processed.head_sha
        active_sha = processed.head_sha

    return history
