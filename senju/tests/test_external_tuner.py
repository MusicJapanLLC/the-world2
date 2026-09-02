from senju.external_tuner import DEFAULT_STATE, tune


def _receipt(*, ok: bool = True, status: int = 200, attempts: int = 1):
    return {
        "provider_acknowledged": ok,
        "status": status,
        "attempt_count": attempts,
    }


def test_degraded_contact_increases_resilience_without_scope_changes():
    state = dict(DEFAULT_STATE)
    out = tune(state, [_receipt(attempts=2)])
    assert out["timeout_seconds"] > state["timeout_seconds"]
    assert out["retries"] >= state["retries"]
    assert "allow_hosts" not in out
    assert "allowed_methods" not in out


def test_tuner_clamps_resilience_bounds():
    state = dict(DEFAULT_STATE, timeout_seconds=15.0, retries=3)
    out = tune(state, [_receipt(ok=False, status=503, attempts=3)])
    assert out["timeout_seconds"] == 15.0
    assert out["retries"] == 3


def test_sustained_health_reduces_latency_budget_gradually():
    state = dict(DEFAULT_STATE, healthy_streak=3, timeout_seconds=5.0, retries=2)
    out = tune(state, [_receipt(), _receipt()])
    assert out["timeout_seconds"] == 4.5
    assert out["retries"] >= 1
    assert out["healthy_streak"] == 0


def test_healthy_contact_holds_strategy_before_streak_threshold():
    state = dict(DEFAULT_STATE, healthy_streak=1, timeout_seconds=5.0, retries=2)
    out = tune(state, [_receipt(), _receipt()])
    assert out["timeout_seconds"] == 5.0
    assert out["retries"] == 2
    assert out["healthy_streak"] == 2
