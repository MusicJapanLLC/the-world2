"""Autonomy Engine — closed-loop execution: ACT -> VERIFY -> LOG -> LEARN -> PROPOSE NEXT."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any

from ..config import SenjuConfig
from ..evaluator import evaluate
from ..memory import load_state, save_state, seeded_population
from ..tournament import Tournament, TournamentReport
from .queue import AutonomyQueue, WorkItem, WorkItemStatus


@dataclasses.dataclass
class AutonomyCycleResult:
    item_id: str
    hypothesis: str
    status: str
    matches_run: int
    red_champion_rating: float
    blue_champion_rating: float
    report_path: str
    proposed_next_items: list[str] = dataclasses.field(default_factory=list)


class AutonomyEngine:
    """Executes closed-loop bounded autonomous learning cycles."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.queue = AutonomyQueue(self.state_dir / "autonomy_queue.json")
        self.state_file = self.state_dir / "champion.json"
        self._ensure_seed_items()

    def _ensure_seed_items(self) -> None:
        """Seed the queue with initial high-impact hypotheses if empty."""
        if len(self.queue._items) > 0:
            return
        initial_hypotheses = [
            WorkItem(
                item_id="hyp-combat-chaining-01",
                hypothesis="High recon_depth combined with chain_synergy increases RED exploitation depth against complex surfaces",
                category="combat_tactics",
                expected_value=0.85,
                cost_budget_matches=300,
                parameters={"population": 40, "generations": 15, "matches": 300, "mutation_rate": 0.08},
            ),
            WorkItem(
                item_id="hyp-blue-telemetry-01",
                hypothesis="Blue early_warning coupled with adaptive_isolation effectively mitigates multi-stage attack chains",
                category="combat_tactics",
                expected_value=0.80,
                cost_budget_matches=300,
                parameters={"population": 40, "generations": 15, "matches": 300, "mutation_rate": 0.08},
            ),
            WorkItem(
                item_id="hyp-ai-agent-cluster-01",
                hypothesis="Simulated AI Agent Cluster targets create realistic pressure on prompt_injection and tool_misuse defenses",
                category="threat_intel",
                expected_value=0.90,
                cost_budget_matches=400,
                authority_scope="threat_intel_public",
                parameters={"population": 50, "generations": 20, "matches": 400, "mutation_rate": 0.10},
            ),
        ]
        for item in initial_hypotheses:
            self.queue.enqueue(item)

    def _execute_real_surface_followup(self, item: WorkItem) -> AutonomyCycleResult:
        """Have Senju re-attack a real guard family after adversary feedback.

        This stays repository-local: the real guard implementations run, while the
        adversary harness keeps its final external transport seam inert.
        """
        from ..real_surface_adversary import run as run_real_surface_adversary

        params = item.parameters
        focus_target = str(params.get("focus_target", "")).strip()
        focus_probe = str(params.get("focus_probe", "")).strip()
        family = str(params.get("focus_family", "")).strip()
        if not focus_target or not focus_probe:
            self.queue.record_result(
                item.item_id,
                success=False,
                blocker_reason="real_surface_followup requires focus_target and focus_probe",
            )
            return AutonomyCycleResult(
                item_id=item.item_id,
                hypothesis=item.hypothesis,
                status=WorkItemStatus.FAILED.value,
                matches_run=0,
                red_champion_rating=1000.0,
                blue_champion_rating=1000.0,
                report_path="",
            )

        report = run_real_surface_adversary()
        rows = report.get("results", [])
        matched: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or str(row.get("target", "")) != focus_target:
                    continue
                name = str(row.get("name", ""))
                if name == focus_probe or (family and name.startswith(family)):
                    matched.append(dict(row))

        passed = bool(matched) and all(row.get("passed") is True for row in matched)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        report_dir = self.state_dir / "autonomy_reports" / "adversary_feedback"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"followup_{item.item_id}_{timestamp}.json"
        evidence = {
            "schema": "senju-adversary-feedback-followup/v1",
            "item_id": item.item_id,
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "focus_target": focus_target,
            "focus_probe": focus_probe,
            "focus_family": family,
            "source_effect_id": params.get("source_effect_id", ""),
            "observed_effect": params.get("observed_effect", ""),
            "matched_probe_count": len(matched),
            "passed": passed,
            "matched_results": matched,
        }
        report_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.queue.record_result(
            item.item_id,
            success=passed,
            result_ref=str(report_file) if passed else "",
            blocker_reason="" if passed else "Senju follow-up found a real-surface regression",
        )

        proposed: list[str] = []
        depth_raw = params.get("feedback_depth", 0)
        depth = depth_raw if isinstance(depth_raw, int) and not isinstance(depth_raw, bool) else 0
        if not passed and depth < 2:
            next_item = WorkItem(
                item_id=f"adv-feedback-retry-{timestamp}",
                hypothesis=(
                    f"Senju follow-up on {focus_target}/{focus_probe} still fails; repeat the "
                    "adjacent real-surface family with elevated attention"
                ),
                category="red_team",
                expected_value=1.0,
                cost_budget_matches=20,
                runtime_seconds_budget=240.0,
                max_retries=3,
                authority_scope="none",
                prerequisite_evidence=[str(report_file)],
                parameters={
                    "runner": "real_surface_followup",
                    "focus_target": focus_target,
                    "focus_probe": focus_probe,
                    "focus_family": family,
                    "source_effect_id": params.get("source_effect_id", ""),
                    "observed_effect": params.get("observed_effect", ""),
                    "feedback_depth": depth + 1,
                },
            )
            if self.queue.enqueue(next_item):
                proposed.append(next_item.item_id)

        return AutonomyCycleResult(
            item_id=item.item_id,
            hypothesis=item.hypothesis,
            status=WorkItemStatus.COMPLETED.value if passed else WorkItemStatus.FAILED.value,
            matches_run=len(matched),
            red_champion_rating=1000.0,
            blue_champion_rating=1000.0,
            report_path=str(report_file),
            proposed_next_items=proposed,
        )

    def execute_next_cycle(self, max_matches: int = 2000) -> AutonomyCycleResult | None:
        """Execute one bounded autonomous experiment cycle."""
        item = self.queue.select_next(budget_matches=max_matches)
        if not item:
            return None

        if item.parameters.get("runner") == "real_surface_followup":
            return self._execute_real_surface_followup(item)

        cfg = SenjuConfig()
        params = item.parameters
        cfg.evolution.population_size = params.get("population", 40)
        cfg.evolution.generations = params.get("generations", 10)
        cfg.evolution.matches_per_generation = params.get("matches", 200)
        cfg.evolution.mutation_rate = params.get("mutation_rate", 0.08)

        # 1. ACT & VERIFY: Run tournament
        import random
        from ..evolution import seed_population
        from ..memory import agent_to_dict

        state = load_state(self.state_file) if self.state_file.exists() else {"version": 1, "history": []}
        tournament = Tournament(cfg)
        base_seed = cfg.evolution.seed if cfg.evolution.seed is not None else 42
        rng = random.Random(base_seed + 1337)

        red = seeded_population(state.get("red_champion"), "red", cfg.evolution.population_size, cfg.evolution.mutation_rate, rng)
        if not red:
            red = seed_population("red", cfg.evolution.population_size, rng)

        blue = seeded_population(state.get("blue_champion"), "blue", cfg.evolution.population_size, cfg.evolution.mutation_rate, rng)
        if not blue:
            blue = seed_population("blue", cfg.evolution.population_size, rng)

        report = tournament.run(red=red, blue=blue)
        evaluation = evaluate(report)

        # 2. LOG: Write structured artifact evidence
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_dir = self.state_dir / "autonomy_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"cycle_{item.item_id}_{timestamp}.json"

        eval_passed = evaluation.safe and evaluation.score > 20.0
        total_matches = sum(g.matches for g in report.generations)
        total_red_wins = sum(g.red_wins for g in report.generations)
        total_blue_wins = sum(g.blue_wins for g in report.generations)

        cycle_evidence = {
            "item_id": item.item_id,
            "hypothesis": item.hypothesis,
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "evaluation_passed": eval_passed,
            "evaluation_score": evaluation.score,
            "balance": evaluation.balance,
            "learning_signal": evaluation.learning_signal,
            "rating_gain": evaluation.rating_gain,
            "reason": evaluation.reason,
            "red_rating": report.red_champion.rating if report.red_champion else 1000.0,
            "blue_rating": report.blue_champion.rating if report.blue_champion else 1000.0,
            "matches_total": total_matches,
        }
        report_file.write_text(json.dumps(cycle_evidence, indent=2), encoding="utf-8")

        # 3. LEARN & UPDATE STATE
        if eval_passed and report.red_champion and report.blue_champion:
            state["red_champion"] = agent_to_dict(report.red_champion)
            state["blue_champion"] = agent_to_dict(report.blue_champion)
            save_state(self.state_file, state)
            self.queue.record_result(item.item_id, success=True, result_ref=str(report_file))
        else:
            self.queue.record_result(item.item_id, success=False, blocker_reason=evaluation.reason)

        # 4. PROPOSE NEXT: Synthesize next hypothesis based on outcomes
        next_items = []
        if total_red_wins > total_blue_wins * 1.5:
            next_hyp = WorkItem(
                item_id=f"hyp-blue-counter-{timestamp[-6:]}",
                hypothesis="Countering aggressive RED exploitation requires higher Blue patch_speed and early_warning investment",
                category="combat_tactics",
                expected_value=0.82,
                cost_budget_matches=350,
                parameters={"population": 40, "generations": 15, "matches": 350, "mutation_rate": 0.07},
            )
            if self.queue.enqueue(next_hyp):
                next_items.append(next_hyp.item_id)
        elif total_blue_wins > total_red_wins * 1.5:
            next_hyp = WorkItem(
                item_id=f"hyp-red-evasion-{timestamp[-6:]}",
                hypothesis="Overcoming solid BLUE perimeter defense requires elevating evasion_adapt and stealth over raw skill",
                category="combat_tactics",
                expected_value=0.84,
                cost_budget_matches=350,
                parameters={"population": 40, "generations": 15, "matches": 350, "mutation_rate": 0.09},
            )
            if self.queue.enqueue(next_hyp):
                next_items.append(next_hyp.item_id)

        return AutonomyCycleResult(
            item_id=item.item_id,
            hypothesis=item.hypothesis,
            status=WorkItemStatus.COMPLETED.value if eval_passed else WorkItemStatus.FAILED.value,
            matches_run=total_matches,
            red_champion_rating=report.red_champion.rating if report.red_champion else 1000.0,
            blue_champion_rating=report.blue_champion.rating if report.blue_champion else 1000.0,
            report_path=str(report_file),
            proposed_next_items=next_items,
        )


def run_autonomy_cycle(state_dir: str | Path = "state", max_cycles: int = 1) -> list[AutonomyCycleResult]:
    engine = AutonomyEngine(state_dir)
    results = []
    for _ in range(max_cycles):
        res = engine.execute_next_cycle()
        if not res:
            break
        results.append(res)
    return results
