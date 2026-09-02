"""Hypothesis Validator — tracks PENDING→CONFIRMED/REFUTED across cycles."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any

TRACKER_FILE = "meta_hypothesis_tracker.json"


@dataclasses.dataclass
class TrackedHypothesis:
    hypothesis_id: str
    statement: str
    surfaces: list[str]
    predicted_outcome: str
    confidence: float
    status: str = "pending"
    cycles_elapsed: int = 0
    test_results: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    created_at: str = dataclasses.field(default_factory=lambda: dt.datetime.utcnow().isoformat() + "Z")
    resolved_at: str | None = None


def load_tracker(state_dir: Path) -> dict[str, TrackedHypothesis]:
    path = state_dir / TRACKER_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: TrackedHypothesis(**v) for k, v in raw.items()}
    except Exception:
        return {}


def save_tracker(tracker: dict[str, TrackedHypothesis], state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / TRACKER_FILE).write_text(
        json.dumps({k: dataclasses.asdict(v) for k, v in tracker.items()}, ensure_ascii=False, indent=2))


def register(hypotheses: list[Any], tracker: dict[str, TrackedHypothesis]) -> int:
    added = 0
    for h in hypotheses:
        if h.hypothesis_id not in tracker:
            tracker[h.hypothesis_id] = TrackedHypothesis(
                hypothesis_id=h.hypothesis_id, statement=h.statement, surfaces=h.surfaces,
                predicted_outcome=h.predicted_outcome, confidence=h.confidence)
            added += 1
    return added


def update_from_cycle(tracker: dict[str, TrackedHypothesis], cycle_report: dict[str, Any]) -> list[str]:
    resolved: list[str] = []
    regressions = set()
    for round_report in cycle_report.get("round_reports", []):
        for result in round_report.get("results", []):
            if not result.get("passed", True):
                regressions.add(result.get("target", ""))
    for hid, hyp in tracker.items():
        if hyp.status not in ("pending", "tested"):
            continue
        hyp.cycles_elapsed += 1
        relevant = [s for s in hyp.surfaces if s in regressions]
        if hyp.predicted_outcome in ("regression", "controlled_regression"):
            if relevant:
                hyp.status = "confirmed"
                hyp.confidence = min(0.99, hyp.confidence + 0.1)
                hyp.resolved_at = dt.datetime.utcnow().isoformat() + "Z"
                resolved.append(hid)
            elif hyp.cycles_elapsed >= 3:
                hyp.status = "refuted"
                hyp.confidence = max(0.05, hyp.confidence - 0.2)
                hyp.resolved_at = dt.datetime.utcnow().isoformat() + "Z"
                resolved.append(hid)
        elif hyp.predicted_outcome == "co_regression" and len(relevant) >= 2:
            hyp.status = "confirmed"
            hyp.confidence = min(0.99, hyp.confidence + 0.15)
            hyp.resolved_at = dt.datetime.utcnow().isoformat() + "Z"
            resolved.append(hid)
        hyp.test_results.append({"cycle": hyp.cycles_elapsed, "regressions_seen": relevant, "status_after": hyp.status})
    return resolved


def summarize(tracker: dict[str, TrackedHypothesis]) -> dict[str, Any]:
    confirmed = [h for h in tracker.values() if h.status == "confirmed"]
    refuted = [h for h in tracker.values() if h.status == "refuted"]
    pending = [h for h in tracker.values() if h.status in ("pending", "tested")]
    return {"total": len(tracker), "confirmed": len(confirmed), "refuted": len(refuted), "pending": len(pending),
            "top_confirmed": [{"id": h.hypothesis_id, "confidence": h.confidence, "surfaces": h.surfaces}
                               for h in sorted(confirmed, key=lambda x: -x.confidence)[:5]]}
