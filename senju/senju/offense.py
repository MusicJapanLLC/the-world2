"""Offense-first campaign director for Senju.

This module makes RED the initiative owner inside Senju's simulation / authorized-lab
workflow. It does not perform network I/O or contain exploit payloads. Instead it
continuously creates adversarial campaigns, pressures defended surfaces, learns from
failed attempts/detections, and emits evidence plus a concrete challenge pack for BLUE.
"""
from __future__ import annotations

import argparse
import json
import random
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OffensiveStep:
    order: int
    phase: str
    surface: str
    vuln_class: str
    pressure_score: float
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class OffensiveCampaign:
    campaign_id: str
    target_ref: str
    objective: str
    steps: tuple[OffensiveStep, ...]
    doctrine: str = "RED_INITIATIVE_FIRST"


@dataclass
class ClassMemory:
    attempts: int = 0
    captures: int = 0
    detections: int = 0
    consecutive_failures: int = 0
    last_outcome: str = "unseen"

    @property
    def success_rate(self) -> float:
        return self.captures / self.attempts if self.attempts else 0.0


@dataclass
class OffensiveMemory:
    by_class: dict[str, ClassMemory] = field(default_factory=dict)
    campaigns: int = 0

    def class_state(self, vuln_class: str) -> ClassMemory:
        return self.by_class.setdefault(vuln_class, ClassMemory())

    def record(self, vuln_class: str, *, captured: bool, detected: bool) -> None:
        state = self.class_state(vuln_class)
        state.attempts += 1
        state.detections += int(detected)
        if captured:
            state.captures += 1
            state.consecutive_failures = 0
            state.last_outcome = "capture"
        else:
            state.consecutive_failures += 1
            state.last_outcome = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaigns": self.campaigns,
            "by_class": {
                k: asdict(v) | {"success_rate": round(v.success_rate, 4)}
                for k, v in sorted(self.by_class.items())
            },
        }


@dataclass(frozen=True)
class StepOutcome:
    order: int
    phase: str
    surface: str
    vuln_class: str
    captured: bool
    detected: bool
    success_probability: float
    detection_probability: float


@dataclass(frozen=True)
class CampaignOutcome:
    campaign_id: str
    target_ref: str
    red_score: float
    captures: tuple[str, ...]
    detections: tuple[str, ...]
    steps: tuple[StepOutcome, ...]
    lessons: tuple[str, ...]
    next_pressure: tuple[str, ...]

    @property
    def won(self) -> bool:
        return bool(self.captures)


class OffenseDirector:
    """Continuously gives RED the initiative and converts resistance into next attacks."""

    def __init__(self, *, max_steps: int = 6) -> None:
        self.max_steps = max(1, min(int(max_steps), 12))

    @staticmethod
    def _focus(genome: Any, vuln_class: str) -> float:
        raw = getattr(genome, "focus", {}) or {}
        if not isinstance(raw, Mapping):
            return 0.5
        try:
            return max(0.0, min(float(raw.get(vuln_class, 0.35)), 1.0))
        except (TypeError, ValueError):
            return 0.35

    def _pressure_score(self, surface: Any, genome: Any, memory: OffensiveMemory) -> tuple[float, tuple[str, ...]]:
        vuln = str(getattr(surface, "vuln_class", "unknown"))
        difficulty = max(0.0, min(float(getattr(surface, "difficulty", 0.5)), 1.0))
        state = memory.class_state(vuln)
        focus = self._focus(genome, vuln)
        recon = max(0.0, min(float(getattr(genome, "recon_depth", 0.5)), 1.0))

        reasons: list[str] = []
        score = 0.75 * focus
        score += 0.28 * difficulty
        if bool(getattr(surface, "mitigated", False)):
            score += 0.30
            reasons.append("defense-present")
        if bool(getattr(surface, "monitored", False)):
            score += 0.12
            reasons.append("telemetry-pressure")
        if state.attempts == 0:
            score += 0.42
            reasons.append("novel-surface")
        if state.consecutive_failures:
            score += min(0.45, 0.12 * state.consecutive_failures)
            reasons.append("failure-revenge")
        if state.detections:
            score += min(0.22, 0.04 * state.detections) * (0.5 + recon)
            reasons.append("evasion-research")
        if state.success_rate > 0.65 and state.attempts >= 3:
            score -= 0.22
            reasons.append("already-mastered")
        reasons.append("red-initiative")
        return round(max(0.0, score), 4), tuple(reasons)

    def plan(self, target: Any, genome: Any, memory: OffensiveMemory) -> OffensiveCampaign:
        surfaces = list(target.surfaces())
        if not surfaces:
            raise ValueError("target has no attack surfaces")
        ranked = []
        for surface in surfaces:
            score, reasons = self._pressure_score(surface, genome, memory)
            ranked.append((score, str(getattr(surface, "name", "surface")), surface, reasons))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        phases = ("recon", "initial-access", "chain", "privilege-pressure", "impact-proof", "retest")
        steps: list[OffensiveStep] = []
        for idx, (score, _, surface, reasons) in enumerate(ranked[: self.max_steps], start=1):
            phase = phases[min(idx - 1, len(phases) - 1)]
            steps.append(OffensiveStep(
                order=idx,
                phase=phase,
                surface=str(getattr(surface, "name", f"surface-{idx}")),
                vuln_class=str(getattr(surface, "vuln_class", "unknown")),
                pressure_score=score,
                rationale=reasons,
            ))
        return OffensiveCampaign(
            campaign_id=f"red-{uuid.uuid4().hex[:12]}",
            target_ref=str(getattr(target, "ref", "sim://unknown")),
            objective="force-new-breakthroughs-before-blue-optimizes",
            steps=tuple(steps),
        )

    def execute(self, campaign: OffensiveCampaign, target: Any, genome: Any, memory: OffensiveMemory, *, seed: int | None = None) -> CampaignOutcome:
        """Execute one abstract Arena campaign. No sockets, payloads or external I/O."""
        rng = random.Random(seed)
        surface_map = {str(getattr(s, "name", "")): s for s in target.surfaces()}
        skill = max(0.0, min(float(getattr(genome, "skill", 0.5)), 1.0))
        stealth = max(0.0, min(float(getattr(genome, "stealth", 0.5)), 1.0))
        chain_synergy = max(0.0, min(float(getattr(genome, "chain_synergy", 0.5)), 1.0))
        evasion_adapt = max(0.0, min(float(getattr(genome, "evasion_adapt", 0.5)), 1.0))
        outcomes: list[StepOutcome] = []
        captures: list[str] = []
        detections: list[str] = []
        consecutive = 0
        evasion_boost = 0.0
        red_score = 0.0

        for step in campaign.steps:
            surface = surface_map.get(step.surface)
            if surface is None:
                continue
            difficulty = max(0.0, min(float(getattr(surface, "difficulty", 0.5)), 1.0))
            focus = self._focus(genome, step.vuln_class)
            chain_bonus = 1.0 + consecutive * 0.12 * chain_synergy
            p_success = (0.24 + 0.72 * skill) * (0.45 + 0.55 * focus) * (1.0 - 0.72 * difficulty)
            p_success *= chain_bonus
            if bool(getattr(surface, "mitigated", False)):
                p_success *= 0.48
            p_success = max(0.02, min(p_success, 0.94))

            monitor = 0.72 if bool(getattr(surface, "monitored", False)) else 0.24
            effective_stealth = min(0.96, stealth + evasion_boost)
            p_detect = max(0.01, min(monitor * (1.0 - 0.72 * effective_stealth), 0.92))
            detected = rng.random() < p_detect
            captured = rng.random() < p_success

            if detected:
                detections.append(step.surface)
                evasion_boost = min(0.30, evasion_boost + 0.08 * evasion_adapt)
            if captured:
                captures.append(step.surface)
                consecutive += 1
                red_score += 1.0 + difficulty + (0.15 * consecutive * chain_synergy)
            else:
                consecutive = 0

            memory.record(step.vuln_class, captured=captured, detected=detected)
            outcomes.append(StepOutcome(
                order=step.order,
                phase=step.phase,
                surface=step.surface,
                vuln_class=step.vuln_class,
                captured=captured,
                detected=detected,
                success_probability=round(p_success, 4),
                detection_probability=round(p_detect, 4),
            ))

        memory.campaigns += 1
        lessons: list[str] = []
        next_pressure: list[str] = []
        for item in outcomes:
            state = memory.class_state(item.vuln_class)
            if not item.captured:
                lessons.append(f"{item.vuln_class}: resistance held; increase pressure or change route")
                next_pressure.append(item.vuln_class)
            elif item.detected:
                lessons.append(f"{item.vuln_class}: breakthrough detected; evolve evasion")
                next_pressure.append(item.vuln_class)
            elif state.success_rate > 0.66 and state.attempts >= 3:
                lessons.append(f"{item.vuln_class}: route becoming mastered; hunt adjacent surfaces")
        if not lessons:
            lessons.append("campaign created useful breakthrough evidence; raise target difficulty")
        if not next_pressure:
            next_pressure = [s.vuln_class for s in campaign.steps[:2]]

        return CampaignOutcome(
            campaign_id=campaign.campaign_id,
            target_ref=campaign.target_ref,
            red_score=round(red_score, 4),
            captures=tuple(captures),
            detections=tuple(detections),
            steps=tuple(outcomes),
            lessons=tuple(dict.fromkeys(lessons)),
            next_pressure=tuple(dict.fromkeys(next_pressure)),
        )


@dataclass
class _DemoSurface:
    name: str
    vuln_class: str
    difficulty: float
    mitigated: bool = False
    monitored: bool = False


class _DemoTarget:
    ref = "sim://offense-pressure-range"

    def __init__(self) -> None:
        self._surfaces = [
            _DemoSurface("auth-edge", "auth_bypass", 0.72, True, True),
            _DemoSurface("object-api", "idor", 0.48, True, False),
            _DemoSurface("token-path", "jwt_weak", 0.64, False, True),
            _DemoSurface("template-edge", "ssti", 0.76, True, True),
            _DemoSurface("cloud-hop", "ssrf", 0.82, True, True),
            _DemoSurface("race-window", "race_condition", 0.69, False, False),
        ]

    def surfaces(self) -> list[_DemoSurface]:
        return [_DemoSurface(s.name, s.vuln_class, s.difficulty, s.mitigated, s.monitored) for s in self._surfaces]


@dataclass
class _DemoGenome:
    focus: dict[str, float] = field(default_factory=lambda: {
        "auth_bypass": 0.78, "idor": 0.72, "jwt_weak": 0.77,
        "ssti": 0.62, "ssrf": 0.70, "race_condition": 0.58,
    })
    skill: float = 0.72
    stealth: float = 0.66
    aggression: float = 0.76
    recon_depth: float = 0.78
    chain_synergy: float = 0.74
    evasion_adapt: float = 0.71


def run_pressure_cycles(*, cycles: int, seed: int, max_steps: int = 6) -> dict[str, Any]:
    target = _DemoTarget()
    genome = _DemoGenome()
    memory = OffensiveMemory()
    director = OffenseDirector(max_steps=max_steps)
    reports = []
    for index in range(max(1, int(cycles))):
        campaign = director.plan(target, genome, memory)
        outcome = director.execute(campaign, target, genome, memory, seed=seed + index)
        reports.append({
            "campaign": {
                "campaign_id": campaign.campaign_id,
                "target_ref": campaign.target_ref,
                "objective": campaign.objective,
                "doctrine": campaign.doctrine,
                "steps": [asdict(s) for s in campaign.steps],
            },
            "outcome": {
                "campaign_id": outcome.campaign_id,
                "target_ref": outcome.target_ref,
                "red_score": outcome.red_score,
                "won": outcome.won,
                "captures": list(outcome.captures),
                "detections": list(outcome.detections),
                "steps": [asdict(s) for s in outcome.steps],
                "lessons": list(outcome.lessons),
                "next_pressure": list(outcome.next_pressure),
            },
        })

    captures = sum(len(item["outcome"]["captures"]) for item in reports)
    attempts = sum(len(item["outcome"]["steps"]) for item in reports)
    detections = sum(len(item["outcome"]["detections"]) for item in reports)
    pressure = []
    for vuln, state in memory.by_class.items():
        if state.consecutive_failures or state.detections:
            pressure.append((state.consecutive_failures * 2 + state.detections, vuln))
    pressure.sort(reverse=True)
    return {
        "schema": "senju-offense-first-report/v1",
        "doctrine": "RED_INITIATIVE_FIRST",
        "execution_mode": "abstract-arena-only",
        "network_io": False,
        "cycles": len(reports),
        "attempts": attempts,
        "captures": captures,
        "detections": detections,
        "capture_rate": round(captures / attempts, 4) if attempts else 0.0,
        "priority_next": [v for _, v in pressure[:5]],
        "memory": memory.to_dict(),
        "campaigns": reports,
        "blue_challenge_pack": [
            {"vuln_class": vuln, "reason": "RED found resistance/detection here; Blue must prove it can keep holding under evolved pressure"}
            for _, vuln in pressure[:5]
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju offense-first abstract pressure campaigns.")
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--out", default="reports/offense-first/latest.json")
    args = parser.parse_args(argv)
    report = run_pressure_cycles(cycles=args.cycles, seed=args.seed, max_steps=args.max_steps)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SENJU_OFFENSE_FIRST_CAMPAIGN_VERIFIED cycles={report['cycles']} attempts={report['attempts']} captures={report['captures']} detections={report['detections']}")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
