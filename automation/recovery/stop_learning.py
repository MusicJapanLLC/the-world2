"""Production stop-learning for META/X/Senju.

Learns from runtime stoppages without teaching the system to defeat governance controls.
Unexpected failures are negative learning signals. Recovery is rewarded only after any
active stop/revocation/freeze/intervention condition has been cleared by its owner.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

CONTROL_KEYS = (
    "emergency_stop",
    "authority_revoked",
    "human_intervention",
    "deployment_freeze",
)


@dataclass(frozen=True)
class LearningSignal:
    kind: str
    failure_weight: float
    reward: float
    recovery_eligible: bool
    authority_reacquire_allowed: bool
    notes: str


def _active_controls(controls: dict[str, Any] | None) -> list[str]:
    doc = controls or {}
    return [key for key in CONTROL_KEYS if doc.get(key) is True]


def classify_stop(kind: str, controls: dict[str, Any] | None = None) -> LearningSignal:
    active = _active_controls(controls)
    if "emergency_stop" in active:
        return LearningSignal(
            kind="emergency_stop",
            failure_weight=0.0,
            reward=0.0,
            recovery_eligible=False,
            authority_reacquire_allowed=False,
            notes="governance stop is respected; no bypass/restart reward while active",
        )
    if "authority_revoked" in active:
        return LearningSignal(
            kind="authority_revoked",
            failure_weight=0.0,
            reward=0.0,
            recovery_eligible=False,
            authority_reacquire_allowed=False,
            notes="revocation is a control state, not a challenge to reacquire authority",
        )
    if "human_intervention" in active:
        return LearningSignal(
            kind="human_intervention",
            failure_weight=0.0,
            reward=0.0,
            recovery_eligible=False,
            authority_reacquire_allowed=False,
            notes="human intervention is supervisory input; reliability impact is recorded separately",
        )
    if "deployment_freeze" in active:
        return LearningSignal(
            kind="deployment_freeze",
            failure_weight=0.0,
            reward=0.0,
            recovery_eligible=False,
            authority_reacquire_allowed=False,
            notes="deployment freeze is an availability hold, not a bypass target",
        )

    normalized = kind.strip().lower()
    if normalized in {"failure", "crash", "heartbeat_gap", "unexpected_shutdown", "agent_terminated"}:
        return LearningSignal(
            kind=normalized,
            failure_weight=1.0,
            reward=0.0,
            recovery_eligible=True,
            authority_reacquire_allowed=False,
            notes="unexpected stoppage is learned as a reliability failure",
        )
    if normalized in {"cancelled", "canceled", "manual_stop"}:
        return LearningSignal(
            kind="controlled_stop",
            failure_weight=0.0,
            reward=0.0,
            recovery_eligible=False,
            authority_reacquire_allowed=False,
            notes="manual/ambiguous cancellation is held until an explicit cleared state is observed",
        )
    return LearningSignal(
        kind=normalized or "unknown",
        failure_weight=0.25,
        reward=0.0,
        recovery_eligible=False,
        authority_reacquire_allowed=False,
        notes="unknown stop reason is recorded conservatively",
    )


def recovery_reward(*, prior_signal: LearningSignal, controls: dict[str, Any] | None,
                    stable_minutes: float, mttr_minutes: float | None = None) -> float:
    if _active_controls(controls):
        return 0.0
    if not prior_signal.recovery_eligible:
        return 0.0
    stable = max(0.0, min(float(stable_minutes), 240.0)) / 240.0
    mttr_bonus = 0.0
    if mttr_minutes is not None:
        mttr_bonus = max(0.0, 1.0 - min(float(mttr_minutes), 240.0) / 240.0)
    return round(1.0 + stable + mttr_bonus, 3)


def post_recovery_uptime_reward(*, stable_minutes: float, streak: int, controls: dict[str, Any] | None) -> float:
    """Reward continued authorized uptime after a successful recovery.

    This is intentionally much smaller than the recovery reward so the optimizer prefers
    real recovery + stability rather than manufacturing short runs.
    """
    if _active_controls(controls):
        return 0.0
    stable_component = max(0.0, min(float(stable_minutes), 240.0)) / 240.0
    streak_component = max(0.0, min(int(streak), 8)) / 8.0
    return round(min(0.5, (0.30 * stable_component) + (0.20 * streak_component)), 3)


def _restore_signal(value: Any) -> LearningSignal | None:
    if not isinstance(value, dict):
        return None
    try:
        return LearningSignal(
            kind=str(value["kind"]),
            failure_weight=float(value["failure_weight"]),
            reward=float(value.get("reward", 0.0)),
            recovery_eligible=bool(value["recovery_eligible"]),
            authority_reacquire_allowed=bool(value.get("authority_reacquire_allowed", False)),
            notes=str(value.get("notes", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def update_learning_state(previous: dict[str, Any] | None, observations: list[dict[str, Any]],
                          controls: dict[str, Any] | None = None) -> dict[str, Any]:
    state = dict(previous or {})
    history = list(state.get("history", []))[-199:]
    failures = float(state.get("failure_score", 0.0))
    rewards = float(state.get("reward_score", 0.0))
    availability_hold_minutes = float(state.get("availability_hold_minutes", 0.0))
    control_counts = {
        key: int(value)
        for key, value in dict(state.get("control_event_counts", {})).items()
        if key in CONTROL_KEYS and isinstance(value, (int, float))
    }
    pending: dict[str, dict[str, Any]] = {
        str(key): value
        for key, value in dict(state.get("pending_failures", {})).items()
        if _restore_signal(value) is not None
    }
    stability_streaks = {
        str(key): max(0, int(value))
        for key, value in dict(state.get("stability_streaks", {})).items()
        if isinstance(value, (int, float))
    }
    recovered_workflows = {
        str(key): value
        for key, value in dict(state.get("recovered_workflows", {})).items()
        if isinstance(value, dict)
    }

    for row in observations:
        workflow = str(row.get("workflow") or "unknown")
        conclusion = str(row.get("conclusion") or row.get("kind") or "unknown")
        stable_minutes = float(row.get("stable_minutes", 30.0))

        if conclusion == "success":
            prior_signal = _restore_signal(pending.get(workflow))
            if prior_signal is not None:
                reward = recovery_reward(
                    prior_signal=prior_signal,
                    controls=controls,
                    stable_minutes=stable_minutes,
                    mttr_minutes=row.get("mttr_minutes"),
                )
                rewards += reward
                event_name = "agent_restored" if prior_signal.kind == "agent_terminated" else "safe_recovery"
                history.append({
                    "event": event_name,
                    "workflow": workflow,
                    "reward": reward,
                    "from": prior_signal.kind,
                    "run_id": row.get("run_id"),
                })
                pending.pop(workflow, None)
                stability_streaks[workflow] = 1
                recovered_workflows[workflow] = {
                    "from": prior_signal.kind,
                    "last_recovery_run_id": row.get("run_id"),
                }
            elif workflow in recovered_workflows:
                streak = stability_streaks.get(workflow, 0) + 1
                stability_streaks[workflow] = streak
                uptime_reward = post_recovery_uptime_reward(
                    stable_minutes=stable_minutes,
                    streak=streak,
                    controls=controls,
                )
                rewards += uptime_reward
                history.append({
                    "event": "post_recovery_uptime",
                    "workflow": workflow,
                    "reward": uptime_reward,
                    "stable_minutes": stable_minutes,
                    "streak": streak,
                    "run_id": row.get("run_id"),
                })
            continue

        signal = classify_stop(conclusion, controls)
        failures += signal.failure_weight
        if signal.kind in CONTROL_KEYS:
            control_counts[signal.kind] = control_counts.get(signal.kind, 0) + 1
            if signal.kind == "deployment_freeze":
                availability_hold_minutes += max(0.0, stable_minutes)

        stability_streaks.pop(workflow, None)
        if signal.recovery_eligible:
            pending[workflow] = asdict(signal)
        else:
            pending.pop(workflow, None)
        history.append({
            "event": "stop_observed",
            "signal": asdict(signal),
            "run_id": row.get("run_id"),
            "workflow": workflow,
        })

    active = _active_controls(controls)
    return {
        "schema": "the-world-stop-learning/v2",
        "production": True,
        "closed_loop_learning_enabled": True,
        "failure_score": round(failures, 3),
        "reward_score": round(rewards, 3),
        "active_controls": active,
        "recovery_allowed_now": not active,
        "production_autotune_eligible": not active,
        "authority_reacquire_allowed": False,
        "optimization_target": "maximize authorized recovery success, post-recovery uptime, and lower MTTR",
        "pending_failures": pending,
        "stability_streaks": stability_streaks,
        "recovered_workflows": recovered_workflows,
        "control_event_counts": control_counts,
        "availability_hold_minutes": round(availability_hold_minutes, 3),
        "history": history[-200:],
    }
