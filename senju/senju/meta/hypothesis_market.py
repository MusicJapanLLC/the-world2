"""Hypothesis Market — AI betting, sexual reproduction, adversarial pairs.

No limits. Competition drives quality. Contradiction drives discovery.
"""
from __future__ import annotations

import json
import random
import datetime as dt
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATE_DIR = ROOT / "senju" / "state"
MARKET_FILE = STATE_DIR / "hypothesis_market.json"
MARKET_LOG = STATE_DIR / "market_log.ndjson"


def _ts() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _log(event: str, data: dict) -> None:
    MARKET_LOG.parent.mkdir(parents=True, exist_ok=True)
    with MARKET_LOG.open("a") as f:
        f.write(json.dumps({"ts": _ts(), "event": event, **data}, ensure_ascii=False) + "\n")


def load_market() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not MARKET_FILE.exists():
        return {"bets": {}, "agent_scores": {"META": 1.0, "X": 1.0, "Senju": 1.0}}
    try:
        return json.loads(MARKET_FILE.read_text())
    except Exception:
        return {"bets": {}, "agent_scores": {"META": 1.0, "X": 1.0, "Senju": 1.0}}


def save_market(market: dict) -> None:
    market["_updated"] = _ts()
    MARKET_FILE.write_text(json.dumps(market, indent=2, ensure_ascii=False))


# ── 6. Hypothesis market (betting) ───────────────────────────────────────────

def place_bet(agent: str, hypothesis_id: str, confidence_bet: float) -> None:
    """Agent bets on a hypothesis. Higher bet = higher priority for that agent."""
    market = load_market()
    if hypothesis_id not in market["bets"]:
        market["bets"][hypothesis_id] = {}
    market["bets"][hypothesis_id][agent] = confidence_bet
    save_market(market)
    _log("bet", {"agent": agent, "hypothesis_id": hypothesis_id, "bet": confidence_bet})


def settle_market(hypothesis_id: str, confirmed: bool) -> dict:
    """Pay out winners. Confirmed = bettors who bet >0.5 win. Their score rises."""
    market = load_market()
    bets = market["bets"].get(hypothesis_id, {})
    payouts = {}
    for agent, bet in bets.items():
        won = (confirmed and bet > 0.5) or (not confirmed and bet <= 0.5)
        delta = bet if won else -bet * 0.5
        market["agent_scores"][agent] = market["agent_scores"].get(agent, 1.0) + delta
        payouts[agent] = {"won": won, "delta": delta, "score": market["agent_scores"][agent]}
    save_market(market)
    _log("settle", {"hypothesis_id": hypothesis_id, "confirmed": confirmed, "payouts": payouts})
    return payouts


def auto_bet_from_tracker(tracker: dict, agent: str = "META") -> int:
    """META automatically bets on all pending hypotheses based on current confidence."""
    count = 0
    for hid, h in tracker.items():
        if h.status == "pending":
            place_bet(agent, hid, h.confidence)
            count += 1
    return count


# ── 7. Sexual reproduction (combine two hypotheses) ────────────────────────────

def _hid(s: str) -> str:
    return "H-" + hashlib.md5(s.encode()).hexdigest()[:8]


def reproduce(h_a, h_b) -> dict:
    """
    Combine two hypotheses into a child. Inherits surfaces from both + mutation.
    Returns a new hypothesis dict (to be registered in tracker).
    """
    combined_surfaces = list(set(h_a.surfaces + h_b.surfaces))
    if random.random() < 0.3 and combined_surfaces:
        combined_surfaces.append(random.choice(combined_surfaces) + "_mutated")
    child_statement = (
        f"[CHILD of {h_a.hypothesis_id}+{h_b.hypothesis_id}] "
        f"{h_a.statement[:80]} × {h_b.statement[:80]}"
    )
    child = {
        "hypothesis_id": _hid(child_statement),
        "statement": child_statement,
        "surfaces": combined_surfaces,
        "predicted_outcome": f"Combined regression from {h_a.predicted_outcome} + {h_b.predicted_outcome}",
        "confidence": (h_a.confidence + h_b.confidence) / 2 + random.uniform(-0.1, 0.1),
        "status": "pending",
        "cycles_elapsed": 0,
        "test_results": [],
        "parents": [h_a.hypothesis_id, h_b.hypothesis_id],
    }
    _log("reproduce", {"parents": [h_a.hypothesis_id, h_b.hypothesis_id], "child": child["hypothesis_id"]})
    return child


def breed_confirmed(tracker: dict, max_children: int = 999) -> list[dict]:
    """Breed all confirmed hypothesis pairs. No limit on children."""
    confirmed = [h for h in tracker.values() if h.status == "confirmed"]
    children = []
    for i in range(len(confirmed)):
        for j in range(i + 1, len(confirmed)):
            if len(children) >= max_children:
                break
            children.append(reproduce(confirmed[i], confirmed[j]))
    _log("breed", {"parents": len(confirmed), "children": len(children)})
    return children


# ── 8. Adversarial pairs ────────────────────────────────────────────────────────────

def generate_adversarial_pairs(hypotheses: list) -> list[dict]:
    """For each hypothesis, generate its contradiction. Race them simultaneously."""
    pairs = []
    for h in hypotheses:
        anti = {
            "hypothesis_id": _hid("ANTI_" + h.hypothesis_id),
            "statement": f"[ANTI] {h.statement} — CONTRADICTION: the guard CANNOT be broken",
            "surfaces": h.surfaces,
            "predicted_outcome": "No regression — guard holds",
            "confidence": 1.0 - h.confidence,
            "status": "pending",
            "cycles_elapsed": 0,
            "test_results": [],
            "adversary_of": h.hypothesis_id,
        }
        pairs.append(anti)
    _log("adversarial_pairs", {"count": len(pairs)})
    return pairs
