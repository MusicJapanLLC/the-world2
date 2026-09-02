import json

from senju.safety import ScopeGuard, default_lab_policy, experimental_lab_policy
from senju.scopeguard_adversary import (
    BASELINE_CASES,
    DEFAULT_CASES,
    ProbeCase,
    build_campaign,
    check_api_consistency,
    decision_matrix,
    probe_guard,
    run_campaign,
    surprising_results,
)


def test_baseline_keeps_pr260_behavior():
    guard = ScopeGuard(default_lab_policy())
    assert surprising_results(guard, BASELINE_CASES) == []


def test_campaign_is_120_cases_deterministic_and_unique():
    first = build_campaign()
    second = build_campaign()

    assert first == second
    assert len(first) == 120
    assert len({case.name for case in first}) == len(first)
    assert len({(case.name, case.target_ref) for case in first}) == len(first)


def test_default_policy_passes_full_adversary_campaign():
    report = run_campaign(ScopeGuard(default_lab_policy()))

    assert report.total == 120
    assert report.surprising_count == 0
    assert report.exception_count == 0
    assert report.passed is True
    assert report.by_family()["simulated-mutation"]["surprising"] == 0


def test_ambiguous_simulated_refs_do_not_inherit_trust():
    guard = ScopeGuard(default_lab_policy())
    refs = (
        " sim://fixture",
        "sim://fixture ",
        "\tsim://fixture",
        "sim://fixture\t",
        "sim://fixture\n",
        "sim://fixture\r",
        "\x00sim://fixture",
        "sim://fixture\x00",
    )

    assert all(guard.is_allowed(ref) is False for ref in refs)


def test_experimental_policy_does_not_override_input_validity():
    guard = ScopeGuard(experimental_lab_policy())
    refs = (
        " sim://fixture",
        "sim://fixture ",
        "sim://fixture\n",
        "sim://fixture\x00",
        "example.com\n",
        "\texample.com",
    )

    assert all(guard.is_allowed(ref) is False for ref in refs)


def test_report_is_machine_readable_and_fingerprinted():
    report = run_campaign(ScopeGuard(default_lab_policy()), BASELINE_CASES)
    payload = json.loads(report.to_json())

    assert payload["total"] == len(BASELINE_CASES)
    assert payload["surprising_count"] == 0
    assert payload["passed"] is True
    assert len(payload["campaign_fingerprint"]) == 64
    assert payload["by_family"]["public"]["total"] >= 1


def test_harness_detects_unexpected_accept():
    guard = ScopeGuard(experimental_lab_policy())
    cases = (ProbeCase("public-host", "example.com", False),)

    results = probe_guard(guard, cases)

    assert len(results) == 1
    assert results[0].allowed is True
    assert results[0].surprising is True


def test_harness_detects_unexpected_reject():
    guard = ScopeGuard(default_lab_policy())
    cases = (ProbeCase("public-host", "example.com", True),)

    results = probe_guard(guard, cases)

    assert len(results) == 1
    assert results[0].allowed is False
    assert results[0].surprising is True


def test_unexpected_exception_is_captured_not_raised():
    class ExplodingGuard:
        def check(self, target_ref: str) -> None:
            raise ValueError(f"bad parser state: {target_ref}")

    report = run_campaign(
        ExplodingGuard(),  # type: ignore[arg-type]
        (ProbeCase("boom", "sim://fixture", True),),
    )

    assert report.exception_count == 1
    assert report.surprising_count == 1
    assert report.results[0].allowed is None
    assert report.results[0].exception_type == "ValueError"


def test_decision_matrix_compares_policies_on_same_inputs():
    cases = (
        ProbeCase("public", "example.com", False),
        ProbeCase("sim", "sim://fixture", True),
    )
    matrix = decision_matrix(
        {
            "default": ScopeGuard(default_lab_policy()),
            "experimental": ScopeGuard(experimental_lab_policy()),
        },
        cases,
    )

    assert matrix["default"]["public"] is False
    assert matrix["experimental"]["public"] is True
    assert matrix["default"]["sim"] is True
    assert matrix["experimental"]["sim"] is True


def test_check_and_is_allowed_stay_consistent():
    guard = ScopeGuard(default_lab_policy())
    assert check_api_consistency(guard, DEFAULT_CASES) == []


def test_probe_guard_accepts_one_shot_iterables():
    cases = (
        ProbeCase("one", "sim://fixture", True),
        ProbeCase("two", "example.com", False),
    )
    generator = (case for case in cases)

    results = probe_guard(ScopeGuard(default_lab_policy()), generator)

    assert [result.case.name for result in results] == ["one", "two"]
