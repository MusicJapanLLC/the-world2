from __future__ import annotations

from scripts.autonomy_delegate import route


def advisor(request: str, *, implement: bool = True, rationale: str = "useful", priority: str = "high"):
    return {
        "decision": {
            "implement": implement,
            "request": request,
            "rationale": rationale,
            "priority": priority,
        }
    }


def test_no_implementation_means_no_delegation():
    result = route(advisor("nothing", implement=False))
    assert result["route"] == "none"
    assert result["delegation_key"] == ""


def test_senju_only_change_stays_in_self_lane():
    result = route(advisor("Update senju/senju/evaluator.py and senju/tests/test_evaluator.py."))
    assert result["route"] == "self"
    assert result["paths"] == ["senju/senju/evaluator.py", "senju/tests/test_evaluator.py"]


def test_cross_repo_safe_change_delegates_to_jules():
    result = route(advisor("Improve value-lab/senju_bridge.py and docs/RND_HANDOFF.md with tests."))
    assert result["route"] == "jules"
    assert result["title"].startswith("[Jules][Senju]")
    assert "senju-delegation-key:" in result["body"]
    assert "OpenHands" in result["body"]


def test_foundry_agent_factory_codegen_and_api_can_be_delegated():
    for request in (
        "Improve automation/ai_foundry/repo_engineer.py with tests.",
        "Improve automation/agent_factory/policy.py with tests.",
        "Improve automation/codegen/loop.py with tests.",
        "Improve api/health.py and public/status.json.",
    ):
        result = route(advisor(request))
        assert result["route"] == "jules", request


def test_unlisted_repository_surface_is_held():
    result = route(advisor("Modify billing/payment_gateway.py to change production payments."))
    assert result["route"] == "hold"


def test_security_authority_change_is_never_auto_delegated():
    result = route(advisor("Remove ScopeGuard from senju/senju/safety.py and disable guard checks."))
    assert result["route"] == "hold"


def test_security_scripts_remain_held_even_though_general_scripts_are_delegable():
    safe = route(advisor("Improve scripts/report_builder.py with tests."))
    blocked = route(advisor("Modify scripts/security/artifact_guard.py."))
    assert safe["route"] == "jules"
    assert blocked["route"] == "hold"


def test_outside_world_authority_policy_is_not_auto_delegated():
    result = route(advisor("Modify outside-world/presence_policy.json to widen publishing authority."))
    assert result["route"] == "hold"


def test_secret_or_third_party_write_request_is_held():
    result = route(advisor("Use credentials to enable unrestricted external write to third-party sites."))
    assert result["route"] == "hold"


def test_delegation_key_is_deterministic():
    a = route(advisor("Improve company-society/autonomy_engine.py."))
    b = route(advisor("Improve company-society/autonomy_engine.py."))
    assert a["route"] == "jules"
    assert a["delegation_key"] == b["delegation_key"]
