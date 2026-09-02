"""
senju.tournament — 世代を回す司令塔（戦争経済つき）。

各世代で多数の対戦を実施し、ELOと資産を更新し、
破産・飢餓による死と、富める者の繁殖によって個体群を入れ替える。
標的は毎試合 ScopeGuard の検問を受けるため、ラボ外に手は届かない。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .agents.base import Agent, RedGenome, BlueGenome
from .arena import run_match
from .config import ArenaConfig, SenjuConfig
from .economy import (
    charge_upkeep,
    feed_population,
    fund_action_budget,
    is_bankrupt,
    reset_gen_scores,
    score_match,
    total_resources,
)
from .evolution import seed_population
from .safety import ScopeGuard, default_lab_policy
from .scoring import apply_result
from .targets.simulated import SimulatedTarget


@dataclass
class GenerationStats:
    generation: int
    matches: int
    red_wins: int
    blue_wins: int
    draws: int
    red_top_rating: float
    blue_top_rating: float
    red_avg_rating: float
    blue_avg_rating: float
    total_captures: int
    total_detections: int
    # 経済指標
    red_resources: float
    blue_resources: float
    red_deaths: int
    blue_deaths: int
    red_births: int
    blue_births: int
    red_richest: float
    blue_richest: float
    reinforcement: float
    vuln_capture_counts: dict[str, int] = field(default_factory=dict)
    archetype_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class TournamentReport:
    scenario: str
    generations: list[GenerationStats] = field(default_factory=list)
    red_champion: Agent | None = None
    blue_champion: Agent | None = None
    scope_violations: list[str] = field(default_factory=list)


class Tournament:
    def __init__(self, config: SenjuConfig, guard: ScopeGuard | None = None) -> None:
        self.config = config
        self.guard = guard or ScopeGuard(default_lab_policy())
        seed = config.evolution.seed
        self._rng = random.Random(seed)
        start = config.economy.starting_resources
        self.red_pop = self._seed("red", config.evolution.population_size, start)
        self.blue_pop = self._seed("blue", config.evolution.population_size, start)
        # 世界の総資源上限（未指定なら初期総量）。
        if config.economy.total_pool_cap is None:
            config.economy.total_pool_cap = round(
                2 * config.evolution.population_size * start, 2
            )

    def _seed(self, side: str, n: int, resources: float) -> list[Agent]:
        pop = seed_population(side, n, self._rng)
        for a in pop:
            a.resources = resources
        return pop

    def _make_target(self, idx: int) -> SimulatedTarget:
        archetypes = self.config.archetypes or ("web_app",)
        archetype = archetypes[idx % len(archetypes)]
        return SimulatedTarget(
            name=f"{self.config.scenario_name}-{archetype}-{idx}",
            archetype=archetype,
            n_surfaces=8,
            seed=self._rng.randint(0, 10_000_000),
        )

    def run(self, red: list[Agent] | None = None, blue: list[Agent] | None = None) -> TournamentReport:
        if red is not None:
            self.red_pop = red
        if blue is not None:
            self.blue_pop = blue
        report = TournamentReport(scenario=self.config.scenario_name)
        ev = self.config.evolution
        for gen in range(ev.generations):
            stats = self._run_generation(gen)
            report.generations.append(stats)
            if gen < ev.generations - 1:
                self.red_pop, stats.red_births = self._repopulate(self.red_pop, gen + 1)
                self.blue_pop, stats.blue_births = self._repopulate(self.blue_pop, gen + 1)

        report.red_champion = self._champion(self.red_pop)
        report.blue_champion = self._champion(self.blue_pop)
        report.scope_violations = self.guard.violations
        return report

    def _champion(self, pop: list[Agent]) -> Agent:
        alive = [a for a in pop if a.alive] or pop
        # チャンピオン = 生き残りの中で最も富める者（戦争の勝者）。
        return max(alive, key=lambda a: a.resources)

    def _alive(self, pop: list[Agent]) -> list[Agent]:
        return [a for a in pop if a.alive]

    def _run_generation(self, gen: int) -> GenerationStats:
        ev = self.config.evolution
        econ = self.config.economy
        red_wins = blue_wins = draws = 0
        total_captures = total_detections = 0
        red_deaths = blue_deaths = 0
        vuln_counts: dict[str, int] = {}
        archetype_counts: dict[str, int] = {}
        reset_gen_scores(self.red_pop)
        reset_gen_scores(self.blue_pop)

        for m in range(ev.matches_per_generation):
            red_alive = self._alive(self.red_pop)
            blue_alive = self._alive(self.blue_pop)
            if not red_alive or not blue_alive:
                break
            red = self._rng.choice(red_alive)
            blue = self._rng.choice(blue_alive)
            target = self._make_target(m)
            archetype_counts[target.archetype] = archetype_counts.get(target.archetype, 0) + 1

            # 資産で行動予算を賄う（貧困は戦力に直結）。
            match_cfg = ArenaConfig(
                red_action_budget=fund_action_budget(red, self.config.arena.red_action_budget, econ),
                blue_action_budget=fund_action_budget(blue, self.config.arena.blue_action_budget, econ),
                seed=self.config.arena.seed,
            )

            surfaces_by_name = {s.name: s.vuln_class for s in target.surfaces()}
            result = run_match(red, blue, target, self.guard, match_cfg)
            apply_result(red, blue, result.winner)
            margin = abs(result.red_score - result.blue_score)
            score_match(red, blue, result.winner, margin, margin)

            if result.winner == "red":
                red_wins += 1
            elif result.winner == "blue":
                blue_wins += 1
            else:
                draws += 1

            total_captures += len(result.captures)
            total_detections += len(result.detections)
            for cap in result.captures:
                vc = surfaces_by_name.get(cap, "?")
                vuln_counts[vc] = vuln_counts.get(vc, 0) + 1

        # 世代末: 維持費（飢餓）→ 食料配分（戦果に応じた限定資源の奪い合い）→ 餓死判定。
        reinforcement = 0.0
        for pop, side in ((self.red_pop, "red"), (self.blue_pop, "blue")):
            drained = charge_upkeep(self._alive(pop), econ)
            # 食料 = 徴収した維持費の一定割合。戦果に比例して勝者へ配分（敗者は得られない）。
            reinforcement += feed_population(pop, drained * econ.reinforcement_ratio, econ)
            for a in self._alive(pop):
                if is_bankrupt(a, econ):
                    a.alive = False
                    a.death_cause = "starved"
                    if side == "red":
                        red_deaths += 1
                    else:
                        blue_deaths += 1

        return GenerationStats(
            generation=gen,
            matches=ev.matches_per_generation,
            red_wins=red_wins,
            blue_wins=blue_wins,
            draws=draws,
            red_top_rating=max(a.rating for a in self.red_pop),
            blue_top_rating=max(a.rating for a in self.blue_pop),
            red_avg_rating=round(sum(a.rating for a in self.red_pop) / len(self.red_pop), 1),
            blue_avg_rating=round(sum(a.rating for a in self.blue_pop) / len(self.blue_pop), 1),
            total_captures=total_captures,
            total_detections=total_detections,
            red_resources=total_resources(self.red_pop),
            blue_resources=total_resources(self.blue_pop),
            red_deaths=red_deaths,
            blue_deaths=blue_deaths,
            red_births=0,   # _repopulate で埋める
            blue_births=0,
            red_richest=round(max(a.resources for a in self.red_pop), 2),
            blue_richest=round(max(a.resources for a in self.blue_pop), 2),
            reinforcement=round(reinforcement, 2),
            vuln_capture_counts=dict(sorted(vuln_counts.items(), key=lambda kv: -kv[1])),
            archetype_counts=archetype_counts,
        )

    def _repopulate(self, pop: list[Agent], generation: int) -> tuple[list[Agent], int]:
        """
        死んだ個体を、富める生存者の子で補充する。
        繁殖は親の資産を消費し、子はその相続を初期資産として受け取る（総資源は保存）。
        富＝適応度。強い遺伝子だけが子孫を残す。
        """
        ev = self.config.evolution
        econ = self.config.economy
        survivors = self._alive(pop)
        side = pop[0].side

        # 生存者ゼロ = 全滅。少数を初期資産で復活させ、系統を絶やさない。
        if not survivors:
            revived = self._seed(side, max(2, ev.elite_count), econ.starting_resources)
            for a in revived:
                a.generation = generation
            return revived, len(revived)

        # 資産(=戦果)で序列化。富裕な親ほど多く子を残す機会を得る。
        survivors.sort(key=lambda a: a.resources, reverse=True)
        target_size = ev.population_size
        next_gen: list[Agent] = list(survivors)  # 生存者は資産・レートを保持して継続

        need = max(0, target_size - len(next_gen))
        # 繁殖可能な親 = 繁殖コストを払える富裕層。
        breeders = [a for a in survivors if a.resources > econ.reproduction_cost * 1.2]
        if not breeders:
            breeders = survivors[: max(1, len(survivors) // 2)]

        births = 0
        for _ in range(need):
            if len(breeders) >= 2:
                pa, pb = self._rng.sample(breeders, 2)
            else:
                pa = pb = breeders[0]

            # 親が繁殖コストを負担（払えないなら生存継続のみ）。
            if pa.resources <= econ.reproduction_cost:
                continue
            pa.resources -= econ.reproduction_cost
            endowment = econ.reproduction_cost  # 相続（総資源保存）

            if side == "red":
                child_genome: object = RedGenome.breed(pa.genome, pb.genome, ev.mutation_rate, self._rng)  # type: ignore[arg-type]
            else:
                child_genome = BlueGenome.breed(pa.genome, pb.genome, ev.mutation_rate, self._rng)  # type: ignore[arg-type]

            start_rating = round((pa.rating + pb.rating) / 2.0, 1)
            child = Agent(
                genome=child_genome, side=side, rating=start_rating,
                generation=generation, resources=endowment,
            )
            next_gen.append(child)
            births += 1
            # 富を使い切った親は繁殖プールから外す。
            breeders = [a for a in breeders if a.resources > econ.reproduction_cost * 1.2]
            if not breeders:
                breeders = survivors[: max(1, len(survivors) // 2)]

        return next_gen, births
