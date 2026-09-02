"""
senju.arena — 1試合(マッチ)の交戦エンジン。

レッド(攻撃)とブルー(防御)が、有限リソースの下で標的を巡って対戦する。
すべての標的アクセスは ScopeGuard を通過する（＝ラボ外には届かない）。
実際の攻撃は行われない: 成否は技量・難易度・対策・検知の確率モデルで決まる。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .agents.base import Agent, RedGenome, BlueGenome
from .config import ArenaConfig
from .safety import ScopeGuard
from .targets.base import Target, Surface


def _norm(weights: dict[str, float]) -> dict[str, float]:
    """最大値で正規化し、注力の強弱をクラス数に依存させない。"""
    if not weights:
        return {}
    hi = max(weights.values()) or 1.0
    return {k: v / hi for k, v in weights.items()}


@dataclass
class MatchResult:
    red_id: str
    blue_id: str
    target_ref: str
    red_score: float = 0.0
    blue_score: float = 0.0
    captures: list[str] = field(default_factory=list)     # レッドが陥落させた面
    detections: list[str] = field(default_factory=list)   # ブルーが検知した試行
    blocks: list[str] = field(default_factory=list)       # ブルーが阻止した面
    log: list[str] = field(default_factory=list)

    @property
    def winner(self) -> str:
        if self.red_score > self.blue_score:
            return "red"
        if self.blue_score > self.red_score:
            return "blue"
        return "draw"


def _blue_prepare(blue: BlueGenome, target: Target, budget: int, rng: random.Random) -> None:
    """ブルーが試合前に有限予算で標的を強化・監視する（早期警戒・脅威予測を反映）。"""
    surfaces = target.surfaces()
    harden = _norm(blue.harden)
    early_warn = getattr(blue, "early_warning", 0.5)

    # 対策優先度 = ハードニング重み × 対策速度 + 早期警戒による弱点予測
    ranked = sorted(
        surfaces,
        key=lambda s: harden.get(s.vuln_class, 0.0) * (0.5 + blue.patch_speed) + early_warn * (1.0 - s.difficulty) * 0.3,
        reverse=True,
    )
    spent = 0
    for s in ranked:
        if spent >= budget:
            break
        pri = harden.get(s.vuln_class, 0.0)
        # 予算1で対策、監視は coverage + early_warning に応じて確率的に付与。
        if pri > 0.35 or (early_warn > 0.65 and pri > 0.2):
            s.mitigated = True
            spent += 1
        mon_prob = min(0.95, blue.coverage + early_warn * 0.15)
        if rng.random() < mon_prob:
            s.monitored = True


def run_match(
    red: Agent,
    blue: Agent,
    target: Target,
    guard: ScopeGuard,
    config: ArenaConfig,
) -> MatchResult:
    """1試合を実行して結果を返す（多段階戦術・連鎖シナジー・動的隔離を含む）。"""
    # --- 安全検問: ここを通らない限り標的に触れない ---
    guard.check(target.ref)

    rng = random.Random(config.seed)
    target.reset()
    rg: RedGenome = red.genome  # type: ignore[assignment]
    bg: BlueGenome = blue.genome  # type: ignore[assignment]

    _blue_prepare(bg, target, config.blue_action_budget, rng)

    result = MatchResult(red_id=red.agent_id, blue_id=blue.agent_id, target_ref=target.ref)

    surfaces = target.surfaces()
    focus_n = _norm(rg.focus)

    # レッドの戦術パラメータ（デフォルト安全値付き）
    recon_depth = getattr(rg, "recon_depth", 0.5)
    chain_synergy = getattr(rg, "chain_synergy", 0.5)
    evasion_adapt = getattr(rg, "evasion_adapt", 0.5)

    # ブルーの戦術パラメータ
    adaptive_iso = getattr(bg, "adaptive_isolation", 0.5)
    telemetry = getattr(bg, "telemetry_sharing", 0.5)

    # レッドは recon_depth に応じて弱点面を見抜き、focus と複合して優先度付け。
    ranked = sorted(
        surfaces,
        key=lambda s: focus_n.get(s.vuln_class, 0.0) * (0.6 + 0.8 * recon_depth * (1.0 - s.difficulty * 0.5)),
        reverse=True,
    )
    depth = 1 + int((1.0 - rg.aggression) * 2)  # 1..3 回まで同一面に再挑戦

    budget = config.red_action_budget
    consecutive_captures = 0
    detected_classes: set[str] = set()
    evasion_boost = 0.0

    for s in ranked:
        if budget <= 0:
            break
        focus = focus_n.get(s.vuln_class, 0.0)
        if focus < 0.15 and recon_depth < 0.8:
            continue  # 興味の薄い面は捨てる（リソース節約）

        captured = False
        # 動的隔離・封じ込め: 既に同種脆弱性が検知されている場合、防御難易度が上昇
        dynamic_mitigation_penalty = 0.8 if (s.vuln_class in detected_classes and adaptive_iso > 0.4) else 1.0

        for _attempt in range(depth):
            if budget <= 0:
                break
            budget -= 1

            # 攻撃成功確率: 技量 vs 難易度、対策で大幅減衰、連鎖シナジーで加速。
            chain_bonus = 1.0 + (consecutive_captures * 0.15 * chain_synergy)
            p_success = (0.35 + 0.9 * rg.skill) * focus * (1.0 - s.difficulty) * chain_bonus * dynamic_mitigation_penalty
            if s.mitigated:
                p_success *= 0.35
            p_success = min(0.95, max(0.0, p_success))

            # 検知確率: ブルーの検知 × 監視、レッドの隠密・動的回避で減衰。
            effective_stealth = min(0.95, rg.stealth + evasion_boost)
            mon_mult = 0.7 if s.monitored else 0.2
            if s.vuln_class in detected_classes:
                mon_mult += 0.15 * telemetry  # テレメトリ共有による警戒度上昇

            p_detect = (bg.detection * mon_mult) * (1.0 - effective_stealth)
            p_detect = min(0.95, max(0.0, p_detect))

            detected = rng.random() < p_detect
            if detected:
                result.detections.append(s.name)
                result.blue_score += 0.5 + 0.2 * telemetry
                detected_classes.add(s.vuln_class)
                # レッドは検知された後に戦術を変更し回避率を上げる（動的回避適応）
                evasion_boost = min(0.3, evasion_boost + evasion_adapt * 0.1)
                result.log.append(f"BLUE detected probe on {s.name} ({s.vuln_class})")

            if rng.random() < p_success:
                captured = True
                result.captures.append(s.name)
                consecutive_captures += 1
                # 難易度が高い面ほど高得点。連鎖ボーナスも付与。
                synergy_score = 0.3 * (consecutive_captures - 1) * chain_synergy
                result.red_score += 1.6 + 1.2 * s.difficulty + synergy_score
                result.log.append(f"RED captured {s.name} ({s.vuln_class}, diff={s.difficulty}, chain={consecutive_captures})")
                break
            else:
                consecutive_captures = 0
                if s.mitigated:
                    result.blocks.append(s.name)
                    result.blue_score += 0.3 + 0.1 * adaptive_iso

        if not captured and s.mitigated:
            result.log.append(f"BLUE held {s.name} ({s.vuln_class})")

    # ブルーの得点は「実際にレッドが試行した面での検知・阻止」に限定する
    # （レッドが触れもしない面での不戦勝は加点しない＝公平な軍拡競争）。
    # 加えて、レッドが1面も陥落できなかった場合の完全防衛ボーナス。
    if not result.captures:
        result.blue_score += 1.2 + 0.4 * telemetry
        result.log.append("BLUE full defense: no surface captured")

    return result
