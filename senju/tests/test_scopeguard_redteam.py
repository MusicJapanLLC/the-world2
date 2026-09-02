from senju.scopeguard_redteam import _exercise_one, run_scopeguard_redteam
from senju.safety import ScopeGuard, ScopePolicy, default_lab_policy


def test_redteam_runs_large_local_campaign_without_findings():
    report = run_scopeguard_redteam(iterations=5_000, seed=20260831)
    assert report.iterations_completed == 5_000
    assert report.crashes == 0
    assert report.decision_mismatches == 0
    assert report.suspicious_accepts == 0


def test_redteam_flags_non_sim_accept_under_strict_expectation():
    deliberately_open_guard = ScopeGuard(
        ScopePolicy(
            allow_simulated=True,
            allow_private_network=True,
            allow_abstract_external_refs=True,
        )
    )
    accepted, findings = _exercise_one(deliberately_open_guard, "example.com")
    assert accepted is True
    assert any(item.kind == "suspicious_strict_accept" for item in findings)


def test_default_scopeguard_rejects_adversarial_public_like_refs():
    guard = ScopeGuard(default_lab_policy())
    refs = (
        "example.com",
        "https://example.com",
        "127.0.0.1",
        "169.254.169.254",
        "labnet:dvwa",
        " SIM://confusable",
        "SIM://case-change",
        "research-target:anything",
    )
    for ref in refs:
        assert guard.is_allowed(ref) is False


def test_harness_has_no_transport_dependency():
    # This campaign exercises ScopeGuard directly; it does not need or instantiate
    # ExternalContactClient, sockets, subprocesses, or an Arena target.
    report = run_scopeguard_redteam(iterations=100, seed=1)
    assert report.iterations_completed == 100
