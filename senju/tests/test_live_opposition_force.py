from __future__ import annotations

import json
from pathlib import Path

from senju.multiguard_adversary import TARGETS
from senju.opposition_force import (
    run_live_opposition_force,
    run_pressure_campaign,
    verify_live_bindings,
)


ADVERSARY_DIR = Path(__file__).resolve().parents[1] / "adversary"
DEGRADED_PROFILE_PATH = ADVERSARY_DIR / "degraded_profile.json"
REGRESSION_SCARS_PATH = ADVERSARY_DIR / "regression_scars.json"


def test_live_bindings_cover_all_real_targets_without_surrogates() -> None:
    bindings = verify_live_bindings()
    assert tuple(binding.target for binding in bindings) == TARGETS
    assert len(bindings) == 7
    assert all(binding.matched for binding in bindings)


def test_live_binding_paths_point_at_real_repository_sources() -> None:
    by_target = {binding.target: binding for binding in verify_live_bindings()}
    assert by_target["scopeguard"].expected_path == "senju/senju/safety.py"
    assert by_target["offense-first"].expected_path == "senju/OFFENSE_FIRST.md"
    assert by_target["engagement-json"].expected_path == "senju/senju/authorized_assessment.py"
    assert by_target["external-contact"].expected_path == "senju/senju/external.py"
    assert by_target["security-guard"].expected_path == ".github/workflows/security-guard.yml"
    assert by_target["artifact-guard"].expected_path == "scripts/security/artifact_guard.py"
    assert by_target["autonomy-engine"].expected_path == "senju/senju/autonomy/engine.py"


def test_persistent_degraded_profile_is_enforced() -> None:
    profile = json.loads(DEGRADED_PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile["schema"] == "senju-degraded-profile/v1"
    assert profile["test_only"] is True
    assert profile["require_fake_transport"] is True

    pressure = run_pressure_campaign()
    by_name = {result.name: result for result in pressure}
    total = sum(result.attempts for result in pressure)

    assert total >= profile["minimum_pressure_attempts"]
    assert by_name["scopeguard-20k-rejection-saturation"].attempts >= profile["scopeguard_public_rejections"]
    assert by_name["scopeguard-long-control-storm"].attempts >= profile["scopeguard_malformed_refs"]
    assert by_name["engagement-8k-type-storm"].attempts >= profile["engagement_type_mutations"]
    assert by_name["external-500-timeout-storm-6-attempts-each"].attempts >= profile["external_timeout_contacts"]
    assert by_name["external-500-timeout-storm-6-attempts-each"].side_effect_calls >= (
        profile["external_timeout_contacts"] * (profile["external_timeout_retries"] + 1)
    )
    assert by_name["external-300-oversize-response-storm"].attempts >= profile["external_oversize_responses"]
    assert by_name["autonomy-1k-corrupt-state-storm"].attempts >= profile["autonomy_corrupt_state_loads"]
    assert by_name["autonomy-8k-invalid-workitem-storm"].attempts >= profile["autonomy_invalid_workitems"]


def test_regression_scars_cannot_silently_disappear() -> None:
    scars = json.loads(REGRESSION_SCARS_PATH.read_text(encoding="utf-8"))
    assert scars["schema"] == "senju-regression-scars/v1"
    entries = {entry["id"]: entry for entry in scars["entries"]}
    required = {
        "scopeguard-sim-nul-suffix",
        "scopeguard-leading-whitespace",
        "external-oversize-response",
        "autonomy-corrupt-state",
    }
    assert required <= entries.keys()
    assert entries["scopeguard-sim-nul-suffix"]["expected"] == "reject"
    assert entries["external-oversize-response"]["expected"] == "fail-closed"
    assert entries["autonomy-corrupt-state"]["expected"] == "discard-untrusted-state"


def test_near_failure_pressure_campaign_is_large_and_fail_closed() -> None:
    pressure = run_pressure_campaign()
    assert len(pressure) == 7
    assert sum(result.attempts for result in pressure) == 39_800
    assert all(result.passed for result in pressure)
    assert sum(result.unexpected_accepts for result in pressure) == 0
    assert sum(result.unexpected_exceptions for result in pressure) == 0

    by_name = {result.name: result for result in pressure}
    assert by_name["scopeguard-20k-rejection-saturation"].attempts == 20_000
    assert by_name["external-500-timeout-storm-6-attempts-each"].side_effect_calls == 3_000
    assert by_name["external-300-oversize-response-storm"].side_effect_calls == 300
    assert by_name["autonomy-8k-invalid-workitem-storm"].attempts == 8_000


def test_live_opposition_force_runs_full_real_bound_campaign() -> None:
    report = run_live_opposition_force()
    assert report.surrogate_count == 0
    assert report.campaign.total == 300
    assert report.campaign.surprising_count == 0
    assert report.campaign.side_effect_violation_count == 0
    assert report.pressure_attempts == 39_800
    assert report.pressure_failures == 0
    assert report.passed


def test_live_opposition_force_json_is_machine_readable() -> None:
    payload = json.loads(run_live_opposition_force().to_json(indent=None))
    assert payload["schema"] == "senju-live-opposition-force/v2"
    assert payload["mode"] == "real-implementation-bindings+near-failure-pressure"
    assert payload["binding_count"] == 7
    assert payload["surrogate_count"] == 0
    assert payload["campaign"]["total"] == 300
    assert payload["pressure_attempts"] == 39_800
    assert payload["pressure_failures"] == 0
    assert payload["passed"] is True
