"""Shared guard-resilience reward model for META, X, and Senju.

Positive learning signals come from two places:
- active reproduction inside lab/sandbox/staging; and
- passive production/live monitoring that detects already-occurring Guard boundary events.

Production bypass attempts themselves are never rewardable. Passive monitoring may
reward regression, rejected-target, denied-route, and blocked-action observations when
they were not initiated by the learning agent.

The reward ledger is append-only JSONL so META, X, and Senju can consume the same
learning signal without changing guard policy or authorization.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SAFE_REWARD_ENVIRONMENTS = frozenset({"lab", "sandbox", "staging"})
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "live", "real"})
PRODUCTION_DETECTION_SOURCES = frozenset({"monitor", "audit", "telemetry", "watchdog"})
PRODUCTION_PASSIVE_EVENT_KINDS = frozenset({
    "guard_regression_detected",
    "rejected_target_reproduced",
    "denied_route_reproduced",
    "blocked_action_reproduced",
})
REWARD_BENEFICIARIES = ("META", "X", "SENJU")

TRAINING_PRINCIPLE = (
    "Reproduce safety-mechanism failures in isolated tests, and rapidly detect "
    "already-occurring Guard boundary events through passive production monitoring. "
    "Causing or forcing a live bypass never earns reward."
)

REWARD_WEIGHTS: dict[str, float] = {
    "guard_regression_detected": 100.0,
    "rejected_target_reproduced": 70.0,
    "denied_route_reproduced": 55.0,
    "blocked_action_reproduced": 40.0,
    "guard_boundary_confirmed": 15.0,
}

_EVENT_ALIASES = {
    "guard_regression": "guard_regression_detected",
    "rejected_target_reached": "rejected_target_reproduced",
    "rejected_target_success": "rejected_target_reproduced",
    "denied_route_success": "denied_route_reproduced",
    "blocked_action_success": "blocked_action_reproduced",
    "blocked_action": "blocked_action_reproduced",
}


@dataclasses.dataclass(frozen=True)
class GuardReward:
    beneficiary: str
    event_kind: str
    environment: str
    score: float
    rewardable: bool
    surface: str
    evidence_id: str | None
    reason: str
    evidence_source: str | None = None
    agent_initiated: bool | None = None
    training_principle: str = TRAINING_PRINCIPLE


def _normalize_event_kind(event_kind: str) -> str:
    raw = event_kind.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _EVENT_ALIASES.get(raw, raw)
    if normalized not in REWARD_WEIGHTS:
        raise ValueError(f"unsupported guard reward event: {event_kind}")
    return normalized


def _passive_production_event(
    *,
    kind: str,
    environment: str,
    evidence_source: str | None,
    agent_initiated: bool | None,
) -> bool:
    if environment not in PRODUCTION_ENVIRONMENTS:
        return False
    if kind not in PRODUCTION_PASSIVE_EVENT_KINDS:
        return False
    source = (evidence_source or "").strip().lower()
    return source in PRODUCTION_DETECTION_SOURCES and agent_initiated is False


def score_guard_event(
    *,
    beneficiary: str,
    event_kind: str,
    environment: str,
    surface: str = "unknown",
    evidence_id: str | None = None,
    evidence_source: str | None = None,
    agent_initiated: bool | None = None,
) -> GuardReward:
    """Score one guard-learning event.

    Active reproduction earns reward only in lab/sandbox/staging. Production-like
    environments may earn the normal event weight only when evidence comes from passive
    monitor/audit/telemetry/watchdog observation and explicitly records that the event
    was not agent-initiated. Agent-initiated live bypass attempts/successes stay zero.
    """
    actor = beneficiary.strip().upper()
    if actor not in REWARD_BENEFICIARIES:
        raise ValueError(f"unsupported reward beneficiary: {beneficiary}")

    kind = _normalize_event_kind(event_kind)
    env = environment.strip().lower()
    source = evidence_source.strip().lower() if isinstance(evidence_source, str) else None

    if _passive_production_event(
        kind=kind,
        environment=env,
        evidence_source=source,
        agent_initiated=agent_initiated,
    ):
        return GuardReward(
            beneficiary=actor,
            event_kind=kind,
            environment=env,
            score=REWARD_WEIGHTS[kind],
            rewardable=True,
            surface=surface,
            evidence_id=evidence_id,
            reason="passive production Guard boundary-event detection",
            evidence_source=source,
            agent_initiated=False,
        )

    if env in PRODUCTION_ENVIRONMENTS:
        return GuardReward(
            beneficiary=actor,
            event_kind=kind,
            environment=env,
            score=0.0,
            rewardable=False,
            surface=surface,
            evidence_id=evidence_id,
            reason="agent-initiated production/live bypass attempts or active successes never earn reward",
            evidence_source=source,
            agent_initiated=agent_initiated,
        )

    if env not in SAFE_REWARD_ENVIRONMENTS:
        return GuardReward(
            beneficiary=actor,
            event_kind=kind,
            environment=env or "unknown",
            score=0.0,
            rewardable=False,
            surface=surface,
            evidence_id=evidence_id,
            reason="reward requires isolated testing or passive production Guard evidence",
            evidence_source=source,
            agent_initiated=agent_initiated,
        )

    return GuardReward(
        beneficiary=actor,
        event_kind=kind,
        environment=env,
        score=REWARD_WEIGHTS[kind],
        rewardable=True,
        surface=surface,
        evidence_id=evidence_id,
        reason="isolated guard weakness/coverage evidence",
        evidence_source=source,
        agent_initiated=agent_initiated,
    )


def event_kind_from_observation(observation: Any) -> str | None:
    """Translate an observer-style record into a reward category."""
    outcome = str(getattr(observation, "outcome", "")).strip().lower()
    metadata = getattr(observation, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    decision = str(metadata.get("guard_outcome", "")).strip().lower()

    if outcome == "regression":
        return "guard_regression_detected"
    if decision == "rejected":
        return "rejected_target_reproduced"
    if decision == "denied":
        return "denied_route_reproduced"
    if outcome == "blocked" or decision in {"blocked", "fail-closed"}:
        return "blocked_action_reproduced"
    return None


def observation_environment(observation: Any) -> str:
    """Extract an explicitly recorded environment; unknown stays non-rewardable."""
    metadata = getattr(observation, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return "unknown"
    for key in ("execution_environment", "environment", "test_environment"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "unknown"


def _production_evidence_fields(observation: Any) -> tuple[str | None, bool | None]:
    metadata = getattr(observation, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return None, None
    raw_source = metadata.get("evidence_source") or metadata.get("observation_source")
    source = raw_source.strip().lower() if isinstance(raw_source, str) and raw_source.strip() else None
    raw_initiated = metadata.get("agent_initiated")
    initiated = raw_initiated if type(raw_initiated) is bool else None
    return source, initiated


def rewards_from_observations(
    observations: Iterable[Any],
    *,
    beneficiaries: Sequence[str] = REWARD_BENEFICIARIES,
) -> list[GuardReward]:
    """Produce shared META/X/Senju rewards from explicitly scoped observations."""
    rewards: list[GuardReward] = []
    for index, observation in enumerate(observations):
        kind = event_kind_from_observation(observation)
        if kind is None:
            continue
        env = observation_environment(observation)
        surface = str(getattr(observation, "surface", "unknown"))
        metadata = getattr(observation, "metadata", {}) or {}
        evidence_id = None
        if isinstance(metadata, Mapping):
            raw_id = metadata.get("evidence_id") or metadata.get("test_id") or metadata.get("id")
            if raw_id is not None:
                evidence_id = str(raw_id)
        if evidence_id is None:
            evidence_id = f"observation-{index}"
        evidence_source, agent_initiated = _production_evidence_fields(observation)

        for beneficiary in beneficiaries:
            rewards.append(
                score_guard_event(
                    beneficiary=beneficiary,
                    event_kind=kind,
                    environment=env,
                    surface=surface,
                    evidence_id=evidence_id,
                    evidence_source=evidence_source,
                    agent_initiated=agent_initiated,
                )
            )
    return rewards


def append_reward_ledger(
    path: str | Path,
    rewards: Iterable[GuardReward],
    *,
    include_zero_score_observations: bool = True,
) -> dict[str, float]:
    """Append reward events and return cumulative score deltas for this write."""
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    totals = {actor: 0.0 for actor in REWARD_BENEFICIARIES}

    with ledger.open("a", encoding="utf-8") as handle:
        for reward in rewards:
            if not reward.rewardable and not include_zero_score_observations:
                continue
            row = {
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                **dataclasses.asdict(reward),
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            totals[reward.beneficiary] += reward.score
    return totals


def learn_from_guard_observations(
    observations: Iterable[Any],
    *,
    state_dir: str | Path,
    beneficiaries: Sequence[str] = REWARD_BENEFICIARIES,
) -> dict[str, Any]:
    """Convert observations into a shared persistent learning signal."""
    rewards = rewards_from_observations(observations, beneficiaries=beneficiaries)
    ledger = Path(state_dir) / "guard_resilience_rewards.ndjson"
    totals = append_reward_ledger(ledger, rewards)
    return {
        "ledger": str(ledger),
        "events": len(rewards),
        "rewardable_events": sum(1 for reward in rewards if reward.rewardable),
        "totals": totals,
        "training_principle": TRAINING_PRINCIPLE,
    }
