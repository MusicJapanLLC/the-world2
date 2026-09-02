"""Chaos Engine — injects randomness, runs tournaments, enables blind exploration.

No upper limits. Unpredictability is a feature.
"""
from __future__ import annotations

import json
import random
import datetime as dt
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
STATE_DIR = ROOT / "senju" / "state"
CHAOS_LOG = STATE_DIR / "chaos_log.ndjson"


def _ts() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _log(event: str, data: dict) -> None:
    CHAOS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CHAOS_LOG.open("a") as f:
        f.write(json.dumps({"ts": _ts(), "event": event, **data}, ensure_ascii=False) + "\n")


# ── 1. Chaos parameter injection ─────────────────────────────────────────────

def inject_chaos(cmd_set, noise_range: float = 0.5) -> Any:
    """Apply random ±noise_range multiplier to all attack commands. No cap."""
    for cmd in cmd_set.attack_commands:
        factor = 1.0 + random.uniform(-noise_range, noise_range)
        old = cmd.pressure_multiplier
        cmd.pressure_multiplier = max(0.1, cmd.pressure_multiplier * factor)
        cmd.reason += f" [chaos×{factor:.2f}]"
    _log("chaos_inject", {"commands": len(cmd_set.attack_commands), "noise_range": noise_range})
    return cmd_set


# ── 2. Random execution delay ──────────────────────────────────────────────────

def random_delay_seconds(min_s: int = 0, max_s: int = 3600) -> int:
    """Return a random delay. Called after cycle end to schedule next trigger."""
    delay = random.randint(min_s, max_s)
    _log("random_delay", {"delay_seconds": delay})
    return delay


# ── 3. Hypothesis tournament ────────────────────────────────────────────────────

def run_tournament(tracker: dict) -> dict:
    """
    Bracket tournament: pair hypotheses, winner's params overwrite loser's surfaces.
    Winner = higher confidence. Loser gets winner's surface list injected.
    Returns dict of overwrites made.
    """
    pending = [h for h in tracker.values() if h.status == "pending"]
    random.shuffle(pending)
    overwrites = {}
    for i in range(0, len(pending) - 1, 2):
        a, b = pending[i], pending[i + 1]
        winner, loser = (a, b) if a.confidence >= b.confidence else (b, a)
        loser.surfaces = list(set(loser.surfaces + winner.surfaces))
        loser.confidence = max(loser.confidence, winner.confidence * 0.8)
        overwrites[loser.hypothesis_id] = {
            "from": winner.hypothesis_id,
            "new_surfaces": loser.surfaces,
            "new_confidence": loser.confidence,
        }
    _log("tournament", {"matches": len(overwrites)})
    return overwrites


# ── 4. Blind exploration ───────────────────────────────────────────────────────────

def blind_surface_pick(graph, exploration_prob: float = 0.4) -> list[str]:
    """
    With exploration_prob, pick a random low-score surface instead of top.
    Escapes local optima. exploration_prob=1.0 = fully random.
    """
    all_surfaces = list(graph.surface_weakness_scores.items())
    if not all_surfaces:
        return []
    if random.random() < exploration_prob:
        chosen = random.choice(all_surfaces)
        _log("blind_exploration", {"surface": chosen[0], "score": chosen[1]})
        return [chosen[0]]
    top = sorted(all_surfaces, key=lambda x: x[1], reverse=True)[:3]
    return [s[0] for s in top]


# ── 5. Dead hypothesis resurrection ──────────────────────────────────────────────

def resurrect_dead(tracker: dict, resurrection_prob: float = 0.3) -> list[str]:
    """Randomly revive refuted hypotheses with reset confidence. Nothing stays dead."""
    revived = []
    for hid, h in tracker.items():
        if h.status == "refuted" and random.random() < resurrection_prob:
            h.status = "pending"
            h.confidence = 0.4 + random.uniform(0, 0.2)
            h.cycles_elapsed = 0
            revived.append(hid)
    if revived:
        _log("resurrection", {"revived": revived})
    return revived
