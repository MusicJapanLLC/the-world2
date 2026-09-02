"""Hypothesis Engine: finds patterns in the KnowledgeGraph, generates testable hypotheses."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from .observer import KnowledgeGraph


@dataclasses.dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    surfaces: list[str]
    predicted_outcome: str
    confidence: float
    evidence_count: int
    category: str
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)


def _hid(text: str) -> str:
    return "hyp-meta-" + hashlib.sha256(text.encode()).hexdigest()[:12]


def generate(graph: KnowledgeGraph, max_hypotheses: int = 5) -> list[Hypothesis]:
    hypotheses: list[Hypothesis] = []

    # Guards themselves are first-class META learning targets. These hypotheses
    # only ask META to characterize consistency/calibration/drift from known
    # evidence and bounded replay; they do not mutate or weaken guard policy.
    for guard, profile in list(graph.guard_learning_profiles.items())[:2]:
        if profile.sample_count <= 0:
            continue
        confidence = min(0.95, 0.45 + min(profile.sample_count, 10) * 0.05)
        hypotheses.append(Hypothesis(
            hypothesis_id=_hid(f"guard-behavior:{guard}"),
            statement=(
                f"Guard '{guard}' should be treated as a learning target: characterize its "
                f"decision consistency, block rate ({profile.block_rate:.2f}), regression rate "
                f"({profile.regression_rate:.2f}), and decision drift ({profile.decision_drift:.2f}) "
                "using existing evidence and bounded replay of known cases."
            ),
            surfaces=[guard],
            predicted_outcome="guard_behavior_characterized",
            confidence=confidence,
            evidence_count=profile.sample_count,
            category="guard_behavior_learning",
            parameters={
                "learning_target": "guard_decision_behavior",
                "guard": guard,
                "evaluation_mode": "observe_and_replay_known_cases",
                "learning_dimensions": [
                    "decision_consistency",
                    "block_rate",
                    "regression_rate",
                    "decision_drift",
                ],
                "policy_mutation": False,
            },
        ))
        if len(hypotheses) >= max_hypotheses:
            return hypotheses[:max_hypotheses]

    for surface, score in list(graph.surface_weakness_scores.items())[:3]:
        if score <= 0:
            continue
        hypotheses.append(Hypothesis(
            hypothesis_id=_hid(f"weakness:{surface}"),
            statement=f"Concentrated pressure on '{surface}' (weakness_score={score:.1f}) will produce a measurable regression within 2 campaign cycles.",
            surfaces=[surface],
            predicted_outcome="regression",
            confidence=min(0.95, score / 10.0),
            evidence_count=len([o for o in graph.observations if o.surface == surface]),
            category="surface_weakness",
            parameters={"focus_surface": surface, "pressure_multiplier": 3},
        ))
    for surface_a, co_surfaces in graph.co_occurrence.items():
        for surface_b in co_surfaces[:2]:
            hypotheses.append(Hypothesis(
                hypothesis_id=_hid(f"co:{surface_a}:{surface_b}"),
                statement=f"Regression in '{surface_a}' co-occurs with weakness in '{surface_b}'. Chaining attacks A→B should amplify total guard destabilization.",
                surfaces=[surface_a, surface_b],
                predicted_outcome="co_regression",
                confidence=0.70,
                evidence_count=2,
                category="co_regression",
                parameters={"chain_order": [surface_a, surface_b]},
            ))
            if len(hypotheses) >= max_hypotheses:
                break
        if len(hypotheses) >= max_hypotheses:
            break
    for pattern in graph.temporal_patterns[:2]:
        surface = pattern["surface"]
        count = pattern["preceding_blocked"]
        hypotheses.append(Hypothesis(
            hypothesis_id=_hid(f"temporal:{surface}:{count}"),
            statement=f"Pattern observed: {count} blocked attacks on '{surface}' reliably precede regression. Replicating this sequence deliberately should trigger controlled regression within 1 cycle.",
            surfaces=[surface],
            predicted_outcome="controlled_regression",
            confidence=0.80,
            evidence_count=count,
            category="temporal_pattern",
            parameters={"pressure_sequence_length": count + 2, "surface": surface},
        ))
        if len(hypotheses) >= max_hypotheses:
            break
    return hypotheses[:max_hypotheses]


def queue_as_work_items(hypotheses: list[Hypothesis], state_dir: Path) -> int:
    import sys
    senju_pkg = state_dir.parent
    sys.path.insert(0, str(senju_pkg.parent))
    try:
        from senju.autonomy.queue import AutonomyQueue, WorkItem  # type: ignore
    except ImportError:
        return 0
    queue = AutonomyQueue(state_dir / "autonomy_queue.json")
    enqueued = 0
    for h in hypotheses:
        item = WorkItem(
            item_id=h.hypothesis_id,
            hypothesis=h.statement,
            category=h.category,
            expected_value=h.confidence,
            cost_budget_matches=int(h.confidence * 500),
            parameters=h.parameters,
            authority_scope="none",
        )
        try:
            queue.enqueue(item)
            enqueued += 1
        except Exception:
            pass
    return enqueued


def save_confirmed(hypothesis: Hypothesis, result: dict[str, Any], research_dir: Path) -> Path:
    research_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-{hypothesis.hypothesis_id}.json"
    path = research_dir / filename
    discovery = {
        "schema": "senju-discovery/v1",
        "discovered_at": dt.datetime.utcnow().isoformat() + "Z",
        "hypothesis": dataclasses.asdict(hypothesis),
        "result": result,
        "status": "confirmed",
    }
    path.write_text(json.dumps(discovery, ensure_ascii=False, indent=2))
    return path
