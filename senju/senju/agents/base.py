"""
senju.agents.base — 攻防エージェントの遺伝子(genome)と個体定義。

エージェントは「戦略の遺伝子」を持つ数理的個体。
実際の攻撃コードは持たない。持つのは「どの脆弱性クラスをどれだけ狙うか」
「どこにリソースを割くか」といった重み。これが進化の対象になる。
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field

from ..targets.base import VULN_CLASSES


def _rand_weights(rng: random.Random) -> dict[str, float]:
    return {v: round(rng.uniform(0.0, 1.0), 3) for v in VULN_CLASSES}


def _mutate_weights(
    weights: dict[str, float], rate: float, rng: random.Random
) -> dict[str, float]:
    out = {}
    for k, v in weights.items():
        if rng.random() < rate:
            v = min(1.0, max(0.0, v + rng.uniform(-0.3, 0.3)))
        out[k] = round(v, 3)
    return out


def _crossover_weights(
    a: dict[str, float], b: dict[str, float], rng: random.Random
) -> dict[str, float]:
    return {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a}


@dataclass
class RedGenome:
    """攻撃側の戦略遺伝子。"""

    focus: dict[str, float] = field(default_factory=dict)  # 脆弱性クラス別の注力度
    skill: float = 0.5            # 基礎技量 0..1
    stealth: float = 0.5          # 隠密性（高いほどブルーに検知されにくい）0..1
    aggression: float = 0.5       # 積極性（多くの面を浅く突くか、少数を深くか）0..1
    recon_depth: float = 0.5      # 偵察精度（弱点面の特定・優先度適応力）0..1
    chain_synergy: float = 0.5    # 攻撃連鎖力（連続突破時のシナジーボーナス）0..1
    evasion_adapt: float = 0.5    # 動的回避適応（検知後の戦術変更能力）0..1

    @staticmethod
    def random(rng: random.Random) -> "RedGenome":
        return RedGenome(
            focus=_rand_weights(rng),
            skill=round(rng.uniform(0.3, 0.7), 3),
            stealth=round(rng.uniform(0.3, 0.7), 3),
            aggression=round(rng.uniform(0.3, 0.7), 3),
            recon_depth=round(rng.uniform(0.3, 0.7), 3),
            chain_synergy=round(rng.uniform(0.3, 0.7), 3),
            evasion_adapt=round(rng.uniform(0.3, 0.7), 3),
        )

    def mutate(self, rate: float, rng: random.Random) -> "RedGenome":
        def m(x: float) -> float:
            if rng.random() < rate:
                x = min(1.0, max(0.0, x + rng.uniform(-0.2, 0.2)))
            return round(x, 3)

        return RedGenome(
            focus=_mutate_weights(self.focus, rate, rng),
            skill=m(self.skill),
            stealth=m(self.stealth),
            aggression=m(self.aggression),
            recon_depth=m(self.recon_depth),
            chain_synergy=m(self.chain_synergy),
            evasion_adapt=m(self.evasion_adapt),
        )

    @staticmethod
    def breed(a: "RedGenome", b: "RedGenome", rate: float, rng: random.Random) -> "RedGenome":
        child = RedGenome(
            focus=_crossover_weights(a.focus, b.focus, rng),
            skill=a.skill if rng.random() < 0.5 else b.skill,
            stealth=a.stealth if rng.random() < 0.5 else b.stealth,
            aggression=a.aggression if rng.random() < 0.5 else b.aggression,
            recon_depth=a.recon_depth if rng.random() < 0.5 else b.recon_depth,
            chain_synergy=a.chain_synergy if rng.random() < 0.5 else b.chain_synergy,
            evasion_adapt=a.evasion_adapt if rng.random() < 0.5 else b.evasion_adapt,
        )
        return child.mutate(rate, rng)


@dataclass
class BlueGenome:
    """防御側の戦略遺伝子。"""

    harden: dict[str, float] = field(default_factory=dict)  # 脆弱性クラス別の対策優先度
    detection: float = 0.5          # 検知能力 0..1
    patch_speed: float = 0.5        # 対策展開の速さ 0..1
    coverage: float = 0.5           # 監視の広さ 0..1
    early_warning: float = 0.5      # 早期警戒・脅威予測能力 0..1
    adaptive_isolation: float = 0.5 # 動的隔離・封じ込め能力 0..1
    telemetry_sharing: float = 0.5  # 相関分析・情報共有防御力 0..1

    @staticmethod
    def random(rng: random.Random) -> "BlueGenome":
        return BlueGenome(
            harden=_rand_weights(rng),
            detection=round(rng.uniform(0.3, 0.7), 3),
            patch_speed=round(rng.uniform(0.3, 0.7), 3),
            coverage=round(rng.uniform(0.3, 0.7), 3),
            early_warning=round(rng.uniform(0.3, 0.7), 3),
            adaptive_isolation=round(rng.uniform(0.3, 0.7), 3),
            telemetry_sharing=round(rng.uniform(0.3, 0.7), 3),
        )

    def mutate(self, rate: float, rng: random.Random) -> "BlueGenome":
        def m(x: float) -> float:
            if rng.random() < rate:
                x = min(1.0, max(0.0, x + rng.uniform(-0.2, 0.2)))
            return round(x, 3)

        return BlueGenome(
            harden=_mutate_weights(self.harden, rate, rng),
            detection=m(self.detection),
            patch_speed=m(self.patch_speed),
            coverage=m(self.coverage),
            early_warning=m(self.early_warning),
            adaptive_isolation=m(self.adaptive_isolation),
            telemetry_sharing=m(self.telemetry_sharing),
        )

    @staticmethod
    def breed(a: "BlueGenome", b: "BlueGenome", rate: float, rng: random.Random) -> "BlueGenome":
        child = BlueGenome(
            harden=_crossover_weights(a.harden, b.harden, rng),
            detection=a.detection if rng.random() < 0.5 else b.detection,
            patch_speed=a.patch_speed if rng.random() < 0.5 else b.patch_speed,
            coverage=a.coverage if rng.random() < 0.5 else b.coverage,
            early_warning=a.early_warning if rng.random() < 0.5 else b.early_warning,
            adaptive_isolation=a.adaptive_isolation if rng.random() < 0.5 else b.adaptive_isolation,
            telemetry_sharing=a.telemetry_sharing if rng.random() < 0.5 else b.telemetry_sharing,
        )
        return child.mutate(rate, rng)


@dataclass
class Agent:
    """レーティングと成績を持つ個体。"""

    genome: object
    side: str            # "red" or "blue"
    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    rating: float = 1000.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    generation: int = 0
    resources: float = 100.0   # 戦争経済の生存通貨
    alive: bool = True
    death_cause: str = ""      # 'bankrupt' | 'starved' | ''
    gen_score: float = 0.0     # 当世代の戦果（勝ち数ベース、毎世代リセット）

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws
