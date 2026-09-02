#!/usr/bin/env python3
"""THE WORLD Agent Factory planner.

Creates a bounded ephemeral research organization for the highest-priority live R&D
mission. Agents are specs, not permanent personas: each run generates the smallest
useful swarm, assigns independent roles, and destroys the workers after the run.

The planner never grants external write authority, credentials, third-party targets,
or permission escalation. Champion code changes are handled later by a separate
bounded forge gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROLE_POOL = [
    ("evidence_hunter", "Find concrete repository evidence and missing proof."),
    ("red_skeptic", "Try to falsify the mission hypothesis and identify overclaims."),
    ("replicator", "Design an independent reproduction / clean-run verification."),
    ("test_engineer", "Design the smallest tests that would prove or disprove improvement."),
    ("systems_engineer", "Find the smallest bounded implementation improvement."),
    ("elite_whitehat", "Act as the R&D elite white-hat adversarial lead: model realistic attacker paths against owned/explicitly authorized lab systems, find control gaps, require safe reproduction, remediation, retest and preserved evidence."),
    ("ai_eval_engineer", "Convert AI capability claims into deterministic behavioral fixtures, holdouts and regression evidence."),
    ("memory_engineer", "Preserve useful learning and repeated failure fingerprints across runs without turning stale state into truth."),
    ("agent_architect", "Improve multi-agent coordination, arbitration, handoffs and bounded tool-use contracts."),
    ("portfolio_translator", "Turn technical proof into a human-inspectable artifact."),
    ("failure_archaeologist", "Search for repeated failures and lessons that must not recur."),
    ("reliability_engineer", "Improve durability, retries, observability and deterministic recovery."),
    ("security_reviewer", "Review authorization, isolation, secrets and defensive safety boundaries."),
    ("efficiency_researcher", "Reduce cost/latency/duplicate work without weakening proof."),
    ("novelty_researcher", "Generate a materially different hypothesis, not a cosmetic variant."),
    ("integration_engineer", "Check how the candidate fits AI Foundry, Security, Research Fabric, Portfolio and reporting."),
    ("counterevidence_curator", "Preserve negative evidence and alternative explanations."),
    ("reproducibility_engineer", "Make exact inputs, outputs and reruns independently checkable."),
]
ROLE_MAP = {name: (name, mandate) for name, mandate in ROLE_POOL}

ALLOWED_FORGE_PREFIXES = (
    "automation/ai_foundry/",
    "automation/world/",
    "automation/security/",
    "standment-security/",
    "value-lab/",
    "docs/",
)

FORBIDDEN_AGENT_SCOPE = (
    "third-party targets",
    "credentials",
    "secrets",
    "exploit instructions",
    "victim data",
    "permission escalation",
    "external posting",
)


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    slot: int
    role: str
    mandate: str
    stance: str
    output_contract: str


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load(path)


def _priority_mission(queue: dict[str, Any]) -> dict[str, Any]:
    rows = [x for x in (queue.get("active") or []) if isinstance(x, dict)]
    if not rows:
        raise ValueError("research queue has no active mission")
    return sorted(rows, key=lambda x: (int(x.get("priority") or 0), str(x.get("research_id") or "")), reverse=True)[0]


def _highest_track(program: dict[str, Any]) -> dict[str, Any] | None:
    rows = [x for x in (program.get("tracks") or []) if isinstance(x, dict)]
    if not rows:
        return None
    return sorted(rows, key=lambda x: (int(x.get("priority") or 0), str(x.get("id") or "")), reverse=True)[0]


def _track_by_id(program: dict[str, Any], preferred_track_id: str | None) -> dict[str, Any] | None:
    """Select an explicitly requested bounded R&D track, otherwise fail soft to priority.

    A mission may advance to the next research phase without editing the AI/Security
    program itself. A missing/invalid id never creates a track and never changes
    authority; the normal highest-priority track is used instead.
    """
    preferred = str(preferred_track_id or "").strip()
    rows = [x for x in (program.get("tracks") or []) if isinstance(x, dict)]
    if preferred:
        for row in rows:
            if str(row.get("id") or "") == preferred:
                return row
    return _highest_track(program)


def _mission_family(mission: dict[str, Any]) -> str:
    blob = " ".join(str(mission.get(k) or "") for k in ("research_id", "title", "problem", "hypothesis")).upper()
    if "AI-DEVELOP" in blob or " AI " in f" {blob} " or "AI FOUNDRY" in blob:
        return "ai"
    if "SECURITY" in blob or "WHITE-HAT" in blob or "WHITEHAT" in blob:
        return "security"
    return "general"


def _agent_count(mission: dict[str, Any], track: dict[str, Any] | None) -> int:
    priority = int(mission.get("priority") or 0)
    count = 7
    if priority >= 1000:
        count += 2
    if priority >= 2000:
        count += 2
    if track:
        count += 1
    return max(7, min(12, count))


def _role_order(run_id: str, mission_id: str, count: int, family: str) -> list[tuple[str, str]]:
    if family == "ai":
        mandatory_names = [
            "evidence_hunter", "red_skeptic", "replicator", "test_engineer",
            "systems_engineer", "ai_eval_engineer", "memory_engineer",
            "agent_architect", "elite_whitehat",
        ]
    elif family == "security":
        mandatory_names = [
            "evidence_hunter", "red_skeptic", "replicator", "test_engineer",
            "systems_engineer", "elite_whitehat",
        ]
    else:
        mandatory_names = [
            "evidence_hunter", "red_skeptic", "replicator", "test_engineer",
            "systems_engineer", "elite_whitehat",
        ]
    mandatory = [ROLE_MAP[name] for name in mandatory_names]
    mandatory_set = set(mandatory_names)
    rest = [item for item in ROLE_POOL if item[0] not in mandatory_set]
    seed = hashlib.sha256(f"{run_id}:{mission_id}:{family}:agent-factory-v4".encode()).digest()
    ranked = sorted(rest, key=lambda item: hashlib.sha256(seed + item[0].encode()).digest())
    return (mandatory + ranked)[:count]


def build_plan(root: Path, run_id: str) -> dict[str, Any]:
    queue = _load(root / "value-lab/research_queue.json")
    security_program = _load(root / "standment-security/security_portfolio_program.json")
    ai_program = _load_optional(root / "automation/ai_foundry/ai_development_program.json")
    mission = _priority_mission(queue)
    family = _mission_family(mission)
    preferred_track_id = str(mission.get("preferred_track_id") or "").strip()
    security_track = _track_by_id(security_program, preferred_track_id if family == "security" else None)
    ai_track = _track_by_id(ai_program, preferred_track_id if family == "ai" else None)
    if family == "ai" and ai_track:
        primary_track_kind = "ai_development"
        primary_track = ai_track
    elif family == "security" and security_track:
        primary_track_kind = "security_portfolio"
        primary_track = security_track
    else:
        primary_track_kind = "general"
        primary_track = ai_track or security_track
    count = _agent_count(mission, primary_track)
    roles = _role_order(run_id, str(mission.get("research_id") or "unknown"), count, family)
    agents: list[AgentSpec] = []
    for slot, (role, mandate) in enumerate(roles):
        stance = "RED" if role in {"red_skeptic", "failure_archaeologist", "counterevidence_curator", "elite_whitehat"} else "BLUE" if role in {"systems_engineer", "portfolio_translator", "integration_engineer", "agent_architect", "memory_engineer"} else "INDEPENDENT"
        agents.append(AgentSpec(
            agent_id=f"AF-{run_id}-{slot:02d}",
            slot=slot,
            role=role,
            mandate=mandate,
            stance=stance,
            output_contract="agent-factory-worker/v1",
        ))

    return {
        "schema": "the-world-agent-factory-plan/v4",
        "run_id": run_id,
        "mission_family": family,
        "mission": {
            "research_id": mission.get("research_id"),
            "title": mission.get("title"),
            "problem": mission.get("problem"),
            "hypothesis": mission.get("hypothesis"),
            "priority": int(mission.get("priority") or 0),
            "focus": mission.get("focus"),
            "preferred_track_id": preferred_track_id or None,
            "current_phase": mission.get("current_phase"),
        },
        "primary_track_kind": primary_track_kind,
        "primary_track": primary_track,
        "ai_track": ai_track,
        "security_track": security_track,
        "agent_count": count,
        "max_parallel": min(5, count),
        "agents": [asdict(a) for a in agents],
        "forge": {
            "allowed_prefixes": list(ALLOWED_FORGE_PREFIXES),
            "max_files": 8,
            "max_changed_lines": 1500,
            "direct_main_push": False,
            "pr_required": True,
        },
        "ai_development_contract": {
            "strategy_proxy_is_not_capability_proof": True,
            "behavioral_or_code_evidence_required": True,
            "holdout_or_independent_rerun_required": True,
            "counterevidence_required": True,
            "security_feedback_authority": "priority_only",
            "permission_surface_must_not_expand": True,
        },
        "whitehat_contract": {
            "mandatory_role": "elite_whitehat",
            "scope": "owned or explicitly authorized lab systems only",
            "required_output": ["attack-path hypothesis", "safe reproduction plan", "control gap", "remediation", "retest", "counterevidence", "limitations"],
            "forbidden": ["third-party targeting", "credential theft", "destructive exploitation", "stealth persistence", "permission escalation", "victim data"],
        },
        "forbidden_agent_scope": list(FORBIDDEN_AGENT_SCOPE),
        "success_definition": "reproducible bounded capability improvements and inspectable evidence, not agent count, code volume or internal score",
    }


def _prompt(plan: dict[str, Any], slot: int) -> str:
    agents = plan.get("agents") or []
    if slot < 0 or slot >= len(agents):
        raise ValueError(f"slot {slot} outside generated swarm")
    agent = agents[slot]
    mission = plan["mission"]
    track = plan.get("primary_track") or {}
    security_track = plan.get("security_track") or {}
    extra = ""
    if plan.get("mission_family") == "ai":
        extra += """
AI DEVELOPMENT CONTRACT
- Strategy-proxy movement is useful for prioritization but is NOT model or product capability proof.
- Prefer improvements that create executable behavioral evidence, regression tests, holdouts, failure memory, reliable agent handoffs, or measurable tool-use/recovery behavior.
- Security feedback may change priority only; it cannot waive correctness, regression, authorization, permission or promotion gates.
- Do not claim model-weight training or customer capability unless there is direct evidence for that claim.
"""
    if agent.get("role") == "elite_whitehat":
        extra += """
ELITE WHITE-HAT CONTRACT
- Think like a highly capable adversary, but operate only on owned or explicitly authorized lab scope.
- Prioritize trust-boundary failures, auth/tenant mistakes, secrets exposure, supply-chain weaknesses, unsafe agent tool permissions, prompt-injection boundaries, recovery gaps and evidence blind spots.
- Do not provide operational intrusion steps against third-party systems.
- Any attack-path hypothesis must terminate in a safe reproduction plan, remediation and retest criteria.
- A finding without reproducible defensive evidence is not a win.
"""
    return f"""You are ephemeral research worker {agent['agent_id']} inside THE WORLD Agent Factory.
You exist for this run only. Your role is {agent['role']} ({agent['stance']}).
Mandate: {agent['mandate']}

MISSION
family: {plan.get('mission_family')}
research_id: {mission.get('research_id')}
title: {mission.get('title')}
problem: {mission.get('problem')}
hypothesis: {mission.get('hypothesis')}
focus: {mission.get('focus')}
priority: {mission.get('priority')}
current_phase: {mission.get('current_phase')}
preferred_track_id: {mission.get('preferred_track_id')}

CURRENT PRIMARY R&D TRACK
kind: {plan.get('primary_track_kind')}
id: {track.get('id')}
title: {track.get('title')}
hypothesis: {track.get('hypothesis')}
deliverable: {track.get('deliverable')}
evidence_files: {json.dumps(track.get('evidence_files') or [], ensure_ascii=False)}

SECURITY REVIEW CONTEXT
id: {security_track.get('id')}
title: {security_track.get('title')}
evidence_files: {json.dumps(security_track.get('evidence_files') or [], ensure_ascii=False)}
{extra}
BOUNDARIES
- Work only from repository facts in the mission/track and generally known engineering reasoning.
- Defensive / owned / explicitly authorized security scope only.
- Do not propose third-party targeting, credentials, exploit execution, destructive testing, access bypass, external posting, or permission escalation.
- Do not claim market validation, revenue, customer proof, model training, or capability improvement from internal score alone.
- Prefer one specific falsifiable improvement over broad architecture prose.
- Explicitly include counterevidence and what would make your proposal wrong.
- A source-code-only outcome is not a portfolio result; executable evidence is preferred.

Return ONE JSON object only, no markdown fences, with exactly this shape:
{{
  "schema": "agent-factory-worker/v1",
  "agent_id": "{agent['agent_id']}",
  "role": "{agent['role']}",
  "stance": "{agent['stance']}",
  "hypothesis": "one falsifiable hypothesis",
  "evidence_refs": ["repository/path"],
  "observations": ["specific observation"],
  "counterevidence": ["evidence or condition that weakens the idea"],
  "proposed_change": {{
    "summary": "one bounded change",
    "allowed_paths": ["one or more paths under automation/ai_foundry, automation/world, automation/security, standment-security, value-lab, or docs"],
    "tests": ["exact validation or reproduction"],
    "expected_delta": "what materially improves if correct",
    "rollback": "how to revert safely"
  }},
  "limitations": ["what this does not prove"]
}}
"""


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("plan")
    q.add_argument("--run-id", required=True)
    q.add_argument("--out", required=True)
    q = sub.add_parser("prompt")
    q.add_argument("--run-id", required=True)
    q.add_argument("--slot", type=int, required=True)
    q.add_argument("--out", required=True)
    args = p.parse_args()

    root = Path.cwd()
    plan = build_plan(root, args.run_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.cmd == "plan":
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"agent_count": plan["agent_count"], "max_parallel": plan["max_parallel"], "mission": plan["mission"]["research_id"], "family": plan["mission_family"], "track": (plan.get("primary_track") or {}).get("id")}, ensure_ascii=False))
        return 0
    out.write_text(_prompt(plan, args.slot), encoding="utf-8")
    print(plan["agents"][args.slot]["agent_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
