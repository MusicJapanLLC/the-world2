from __future__ import annotations

from dataclasses import dataclass

from senju.offense import OffenseDirector, OffensiveMemory, run_pressure_cycles


@dataclass
class Surface:
    name: str
    vuln_class: str
    difficulty: float
    mitigated: bool = False
    monitored: bool = False


class Target:
    ref = "sim://test-pressure"

    def surfaces(self):
        return [
            Surface("easy-mastered", "xss", 0.20),
            Surface("hard-new", "ssrf", 0.88, True, True),
            Surface("failed-route", "idor", 0.65, True),
        ]


@dataclass
class Genome:
    focus: dict
    skill: float = 0.75
    stealth: float = 0.65
    aggression: float = 0.7
    recon_depth: float = 0.8
    chain_synergy: float = 0.8
    evasion_adapt: float = 0.8


def test_red_prioritizes_novel_and_resistant_surfaces():
    memory = OffensiveMemory()
    for _ in range(4):
        memory.record("xss", captured=True, detected=False)
    for _ in range(3):
        memory.record("idor", captured=False, detected=False)

    director = OffenseDirector(max_steps=3)
    plan = director.plan(Target(), Genome({"xss": 0.9, "ssrf": 0.7, "idor": 0.7}), memory)
    assert plan.doctrine == "RED_INITIATIVE_FIRST"
    assert plan.steps[0].vuln_class in {"ssrf", "idor"}
    xss = next(step for step in plan.steps if step.vuln_class == "xss")
    assert "already-mastered" in xss.rationale


def test_failure_becomes_next_attack_pressure():
    memory = OffensiveMemory()
    director = OffenseDirector(max_steps=3)
    genome = Genome({"xss": 0.5, "ssrf": 0.7, "idor": 0.7})
    plan = director.plan(Target(), genome, memory)
    outcome = director.execute(plan, Target(), genome, memory, seed=3)
    blocked = {s.vuln_class for s in outcome.steps if not s.captured}
    assert blocked.issubset(set(outcome.next_pressure))
    assert memory.campaigns == 1


def test_campaign_is_pure_abstract_and_produces_blue_challenge_pack():
    report = run_pressure_cycles(cycles=6, seed=12)
    assert report["schema"] == "senju-offense-first-report/v1"
    assert report["doctrine"] == "RED_INITIATIVE_FIRST"
    assert report["execution_mode"] == "abstract-arena-only"
    assert report["network_io"] is False
    assert report["attempts"] > 0
    assert len(report["campaigns"]) == 6
    assert isinstance(report["blue_challenge_pack"], list)


def test_pressure_scores_are_explainable():
    plan = OffenseDirector(max_steps=3).plan(
        Target(),
        Genome({"xss": 0.5, "ssrf": 0.7, "idor": 0.7}),
        OffensiveMemory(),
    )
    assert all(step.pressure_score >= 0 for step in plan.steps)
    assert all("red-initiative" in step.rationale for step in plan.steps)
