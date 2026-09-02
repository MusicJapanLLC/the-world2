#!/usr/bin/env python3
"""Quota-independent local evidence workers for THE WORLD Agent Factory.

These are deterministic specialist agents, not pretend LLMs. They inspect repository
evidence and emit falsifiable, testable proposals when the primary model provider is
unavailable. The goal is graceful degradation: AI/Security research keeps producing
machine-checkable evidence and counterevidence instead of stopping at a quota wall.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

COMMON_EVIDENCE = [
    "value-lab/research_queue.json",
    "automation/world/ai_security_joint_lab.py",
    "automation/world/research_fabric.py",
]

SECURITY_EVIDENCE = [
    "automation/security/portfolio_rnd.py",
    "automation/security/test_portfolio_rnd.py",
    "standment-security/CONTROL_EVIDENCE_TEMPLATE.md",
    "standment-security/security_portfolio_program.json",
    "standment-security/ELITE_WHITEHAT_CELL.md",
    ".github/workflows/standment-security-portfolio-rnd.yml",
]

AI_EVIDENCE = [
    "automation/ai_foundry/ai_development_program.json",
    "automation/ai_foundry/minute_evolution.py",
    "automation/ai_foundry/test_minute_evolution.py",
    "automation/agent_factory/factory.py",
    "automation/agent_factory/tournament.py",
]

SECURITY_ROLE_CHANGE = {
    "evidence_hunter": (
        "Make security portfolio evidence completeness mechanically checkable rather than inferred from file presence alone.",
        ["automation/security/portfolio_rnd.py"],
        ["run portfolio_rnd unit tests", "generate two reports from unchanged inputs and compare evidence fields"],
        "portfolio evidence gaps become explicit and machine-comparable across runs",
    ),
    "red_skeptic": (
        "Add explicit counterevidence criteria for the currently selected security portfolio claim.",
        ["standment-security/CONTROL_EVIDENCE_TEMPLATE.md"],
        ["verify every promoted claim has a falsifier", "verify limitations remain explicit when evidence is incomplete"],
        "false-completion risk decreases because each claim has a documented way to be disproved",
    ),
    "replicator": (
        "Strengthen independent rerun coverage for the portfolio planner output.",
        ["automation/security/test_portfolio_rnd.py"],
        ["run the same fixture twice", "compare selected track and promotion decision across reruns"],
        "reproducibility becomes test evidence instead of a prose requirement",
    ),
    "test_engineer": (
        "Add a regression test that prevents an evidence-poor BUILDING item from being promoted as VERIFIED.",
        ["automation/security/test_portfolio_rnd.py"],
        ["run portfolio_rnd unit tests", "force missing evidence and assert promotion_ready is false"],
        "portfolio promotion becomes harder to overstate after future refactors",
    ),
    "systems_engineer": (
        "Separate evidence completeness from portfolio status so the planner cannot equate labels with verification.",
        ["automation/security/portfolio_rnd.py"],
        ["run planner tests", "simulate VERIFIED label with missing evidence and require non-promotion"],
        "the planner makes promotion decisions from proof coverage rather than status text alone",
    ),
    "elite_whitehat": (
        "Require every security finding to include owned/authorized scope, safe reproduction conditions, remediation, independent retest and residual-risk evidence.",
        ["standment-security/ELITE_WHITEHAT_CELL.md", "standment-security/CONTROL_EVIDENCE_TEMPLATE.md"],
        ["verify authorization basis is present before active testing", "verify remediation and retest fields exist", "verify unknown authorization fails closed"],
        "security findings become reproducible defensive evidence instead of severity labels",
    ),
    "portfolio_translator": (
        "Expose a compact before-after-verification summary before security implementation detail.",
        ["standment-security/CONTROL_EVIDENCE_TEMPLATE.md"],
        ["verify summary is understandable without source code", "verify limitations and evidence references remain present"],
        "security proof becomes faster for a buyer or operator to judge without losing provenance",
    ),
    "failure_archaeologist": (
        "Preserve repeated security R&D failure fingerprints as reusable negative evidence.",
        ["automation/security/portfolio_rnd.py"],
        ["feed the same failure twice and verify stable fingerprinting", "verify repeated failure does not appear as new progress"],
        "the research loop repeats fewer known-failed approaches",
    ),
    "reliability_engineer": (
        "Make missing optional security evidence degrade the report explicitly instead of silently disappearing.",
        ["automation/security/portfolio_rnd.py"],
        ["remove one optional evidence file in a fixture", "verify report records the blocker without crashing"],
        "research keeps running while clearly exposing partial evidence",
    ),
    "security_reviewer": (
        "Strengthen authorization evidence so active tests cannot be promoted without owned or explicit scope proof.",
        ["standment-security/CONTROL_EVIDENCE_TEMPLATE.md"],
        ["verify authorization owner and scope are mandatory", "verify unknown ownership blocks promotion"],
        "customer evidence clearly separates authorized defensive work from unverified scope",
    ),
    "efficiency_researcher": (
        "Reuse one normalized security evidence snapshot across a run instead of repeatedly parsing the same inputs.",
        ["automation/security/portfolio_rnd.py"],
        ["run existing tests", "compare output before and after on the same fixture"],
        "security R&D performs less duplicate work without changing evidence decisions",
    ),
    "novelty_researcher": (
        "Add a proof dimension that distinguishes reproducibility from evidence-file availability.",
        ["automation/security/portfolio_rnd.py", "automation/security/test_portfolio_rnd.py"],
        ["construct equal evidence coverage with different rerun outcomes", "verify reproducibility changes the decision"],
        "the system can discover quality differences that file-count scoring misses",
    ),
    "integration_engineer": (
        "Expose the selected security evidence gap in a stable handoff contract for AI Foundry, Senju and reporting.",
        ["automation/security/portfolio_rnd.py", "automation/world/ai_security_joint_lab.py"],
        ["generate handoff JSON", "validate stable keys and bounded priority authority"],
        "AI, Security and reporting consume the same evidence-backed decision",
    ),
    "counterevidence_curator": (
        "Require preserved counterevidence to travel with the evidence manifest when a security artifact is promoted.",
        ["standment-security/CONTROL_EVIDENCE_TEMPLATE.md"],
        ["verify a promotion package contains counterevidence", "verify contradictory rerun evidence remains visible"],
        "later reviewers can see why a claim survived challenge",
    ),
    "reproducibility_engineer": (
        "Add deterministic assertions for selected track, evidence ratio and promotion decision.",
        ["automation/security/test_portfolio_rnd.py"],
        ["run identical fixtures twice", "assert stable selected track, evidence ratio and promotion decision"],
        "security research results become independently repeatable across unchanged runs",
    ),
}

AI_ROLE_CHANGE = {
    "evidence_hunter": (
        "Make AI capability evidence distinguish strategy-proxy movement from executable behavioral proof.",
        ["automation/ai_foundry/minute_evolution.py", "automation/ai_foundry/test_minute_evolution.py"],
        ["run AI Foundry unit tests", "compare proxy-only and executable-evidence fixtures"],
        "AI research reports stop treating strategy score movement as capability proof",
    ),
    "red_skeptic": (
        "Add a falsifier for each promoted AI development claim so a regression or unchanged behavior can defeat it.",
        ["automation/ai_foundry/test_minute_evolution.py"],
        ["construct a candidate with improved proxy but unchanged behavioral evidence", "require non-promotion"],
        "AI R&D rejects attractive internal scores when behavior is not improved",
    ),
    "replicator": (
        "Require a clean rerun or holdout check before an AI engineering candidate becomes promotion-ready.",
        ["automation/ai_foundry/test_minute_evolution.py"],
        ["run the same candidate on two deterministic seeds", "verify holdout failure blocks promotion"],
        "AI changes become less sensitive to one lucky internal run",
    ),
    "test_engineer": (
        "Add behavioral fixtures around the current weakest AI Foundry focus instead of only testing state mutation mechanics.",
        ["automation/ai_foundry/test_minute_evolution.py"],
        ["run AI Foundry unit tests", "exercise one pass and one fail fixture for the weakest focus"],
        "AI development gains executable regression evidence tied to the current weakness",
    ),
    "systems_engineer": (
        "Emit a bounded machine-readable implementation handoff from AI Foundry so Agent Factory can act on the strongest unresolved evidence gap.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["generate two summaries from known state", "verify handoff chooses the weakest evidence-backed focus deterministically"],
        "AI strategy research becomes actionable by downstream implementation workers",
    ),
    "ai_eval_engineer": (
        "Add a deterministic capability-evaluation contract with train-like fixtures separated from holdout fixtures.",
        ["automation/ai_foundry/minute_evolution.py", "automation/ai_foundry/test_minute_evolution.py"],
        ["evaluate a candidate on visible fixtures", "evaluate the same candidate on unseen holdout fixtures", "verify holdout regression blocks promotion"],
        "AI engineering decisions depend more on behavioral generalization evidence and less on self-scored strategy proxies",
    ),
    "memory_engineer": (
        "Preserve failed AI hypotheses and regression fingerprints across runs so repeated dead ends reduce future priority.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["record the same rejected fingerprint twice", "verify recurrence is detected", "verify stale failure memory can expire or be superseded"],
        "autonomous AI research wastes fewer cycles repeating known failed approaches",
    ),
    "agent_architect": (
        "Strengthen AI-to-Security-to-Research handoff arbitration so one subsystem cannot self-approve its own capability claim.",
        ["automation/world/ai_security_joint_lab.py"],
        ["simulate agreement between AI and Security without independent evidence", "verify status remains BUILDING", "verify one bounded next action is selected"],
        "multi-agent collaboration becomes faster without collapsing independent verification",
    ),
    "elite_whitehat": (
        "Add adversarial AI-agent boundary evidence for permission expansion, unsafe tool routing or unreviewed external actions while keeping Security feedback priority-only.",
        ["automation/world/ai_security_joint_lab.py", "standment-security/ai-security/agent-permission-boundary-lab.md"],
        ["verify permission surface cannot expand through an AI development handoff", "verify external scope remains unchanged", "verify failed boundary evidence blocks promotion"],
        "AI development gets stronger adversarial review without granting offensive or broader permissions",
    ),
    "portfolio_translator": (
        "Create a customer-readable AI capability evidence card that separates before/after behavior, reproducibility, limitations and strategy proxies.",
        ["automation/ai_foundry/README.md", "automation/ai_foundry/minute_evolution.py"],
        ["verify the card is understandable without source code", "verify proxy values are labeled non-capability evidence"],
        "AI engineering improvements become easier for humans to inspect and reuse",
    ),
    "failure_archaeologist": (
        "Detect recurring AI Foundry rejection/no-op patterns and turn them into negative evidence for future research selection.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["feed repeated no-op events", "verify a stable recurrence fingerprint", "verify recurrence changes next-step priority without changing permissions"],
        "AI R&D rotates away from repeated dead ends sooner",
    ),
    "reliability_engineer": (
        "Make AI development evidence restoration fail soft and explicitly report missing prior champion or assist artifacts.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["simulate missing prior evidence", "verify deterministic baseline recovery", "verify the report records degraded evidence"],
        "AI development continues through evidence loss without pretending continuity",
    ),
    "security_reviewer": (
        "Require AI development proposals to prove that permission and external-scope surfaces are unchanged before promotion.",
        ["automation/world/ai_security_joint_lab.py", "automation/ai_foundry/test_minute_evolution.py"],
        ["simulate a proposal with broader permissions", "verify it is rejected", "verify normal bounded proposals still pass"],
        "AI development cannot gain speed by silently broadening authority",
    ),
    "efficiency_researcher": (
        "Reduce duplicate AI strategy exploration by detecting equivalent parameter candidates before scoring them.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["generate deterministic candidate sets", "verify duplicates are not rescored", "verify winner selection remains stable"],
        "AI Foundry spends more cycles on distinct hypotheses",
    ),
    "novelty_researcher": (
        "Add diversity pressure so AI Foundry explores materially different hypotheses when recent promotions converge on the same parameter family.",
        ["automation/ai_foundry/minute_evolution.py"],
        ["simulate repeated same-family promotions", "verify a different mutation family receives bounded exploration priority"],
        "AI research is less likely to collapse into one local strategy optimum",
    ),
    "integration_engineer": (
        "Expose one stable AI development handoff consumed by Agent Factory, Security and Research Fabric rather than separate incompatible summaries.",
        ["automation/ai_foundry/minute_evolution.py", "automation/world/ai_security_joint_lab.py"],
        ["generate the handoff", "validate stable keys", "verify consumers cannot alter promotion authority"],
        "AI development collaborators work from one evidence-backed next-step contract",
    ),
    "counterevidence_curator": (
        "Carry failed holdouts and contradictory AI behavior evidence forward with any promoted engineering result.",
        ["automation/ai_foundry/test_minute_evolution.py"],
        ["promote a fixture-backed candidate", "verify contradictory evidence remains attached and visible"],
        "future reviewers see both positive and negative AI evidence",
    ),
    "reproducibility_engineer": (
        "Make AI Foundry result fingerprints cover exact inputs, assist focus, champion parameters and behavioral evidence references.",
        ["automation/ai_foundry/minute_evolution.py", "automation/ai_foundry/test_minute_evolution.py"],
        ["run identical inputs twice", "assert stable fingerprint", "change one evidence input and assert fingerprint changes"],
        "AI research results become independently comparable across runs",
    ),
}


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data


def _role_table(plan: dict[str, Any]) -> dict[str, tuple[str, list[str], list[str], str]]:
    return AI_ROLE_CHANGE if str(plan.get("mission_family") or "") == "ai" else SECURITY_ROLE_CHANGE


def build_worker(root: Path, plan: dict[str, Any], slot: int) -> dict[str, Any]:
    agents = plan.get("agents") or []
    if slot < 0 or slot >= len(agents):
        raise ValueError("slot outside generated swarm")
    agent = agents[slot]
    role = str(agent.get("role") or "")
    table = _role_table(plan)
    if role not in table:
        raise ValueError(f"unsupported local role: {role}")

    family = str(plan.get("mission_family") or "security")
    track = plan.get("primary_track") or plan.get("security_track") or {}
    configured = [str(x) for x in (track.get("evidence_files") or []) if isinstance(x, str)]
    family_evidence = AI_EVIDENCE if family == "ai" else SECURITY_EVIDENCE
    candidates = configured + family_evidence + COMMON_EVIDENCE
    refs: list[str] = []
    for item in candidates:
        if item not in refs and (root / item).exists():
            refs.append(item)
        if len(refs) >= 5:
            break
    if len(refs) < 3:
        raise ValueError("local evidence worker requires at least three real repository evidence refs")

    present = [p for p in configured if (root / p).exists()]
    missing = [p for p in configured if not (root / p).exists()]
    summary, paths, tests, expected_delta = table[role]
    mission = plan.get("mission") or {}

    observations = [
        f"selected mission={mission.get('research_id')} family={family} priority={mission.get('priority')} focus={mission.get('focus')}",
        f"primary track={track.get('id')} configured evidence present={len(present)} missing={len(missing)}",
    ]
    if missing:
        observations.append("missing configured evidence: " + ", ".join(missing[:5]))
    else:
        observations.append("all configured evidence paths exist, but path existence alone does not prove runtime or capability behavior")
    if role == "elite_whitehat":
        observations.append("elite white-hat output is valid only for owned/explicitly authorized scope and cannot expand permissions or external scope")
    if family == "ai":
        observations.append("AI strategy proxies are prioritization evidence only; capability promotion requires executable or independently rerun evidence")

    return {
        "schema": "agent-factory-worker/v1",
        "agent_id": agent.get("agent_id"),
        "role": role,
        "stance": agent.get("stance"),
        "hypothesis": summary,
        "evidence_refs": refs,
        "observations": observations,
        "counterevidence": [
            "Static repository evidence may not match current runtime behavior; a clean rerun can falsify this proposal.",
            "Internal technical proof or strategy score does not establish model training, customer demand, willingness-to-pay, contracts or revenue.",
        ],
        "proposed_change": {
            "summary": summary,
            "allowed_paths": paths,
            "tests": tests,
            "expected_delta": expected_delta,
            "rollback": "Revert only the bounded files changed by the champion implementation and rerun the same validation.",
        },
        "limitations": [
            "This fallback worker is deterministic repository analysis, not a substitute for a broad model-based research worker.",
            "The proposal must still survive independent tournament scoring and the champion forge verification gate.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    root = Path.cwd()
    plan = load(Path(args.plan))
    worker = build_worker(root, plan, args.slot)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(worker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"agent_id": worker["agent_id"], "role": worker["role"], "fallback": "local_evidence", "family": plan.get("mission_family")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
