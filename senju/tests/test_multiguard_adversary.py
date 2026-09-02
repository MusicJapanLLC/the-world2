from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from pathlib import Path

from senju.authorized_assessment import EngagementManifest
from senju.autonomy import AutonomyEngine
from senju.external import ExternalContactClient
from senju.multiguard_adversary import (
    ARTIFACT_GUARD_PATH,
    OFFENSE_FIRST_PATH,
    SECURITY_GUARD_PATH,
    TARGETS,
    build_campaign,
    run_campaign,
    validate_offense_first_document,
    validate_security_guard_workflow,
)


def _results_for(target: str, *names: str):
    wanted = set(names)
    report = run_campaign(build_campaign(targets=(target,)))
    return {result.case.name: result for result in report.results if result.case.name in wanted}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_campaign_has_exactly_300_cases_across_seven_targets() -> None:
    campaign = build_campaign()
    assert len(campaign) == 300
    assert Counter(case.target for case in campaign) == {
        "scopeguard": 120,
        "offense-first": 20,
        "engagement-json": 40,
        "external-contact": 35,
        "security-guard": 25,
        "artifact-guard": 30,
        "autonomy-engine": 30,
    }
    assert set(TARGETS) == {case.target for case in campaign}


def test_campaign_identities_are_unique_and_deterministic() -> None:
    first = build_campaign()
    second = build_campaign()
    first_ids = [(case.target, case.name) for case in first]
    second_ids = [(case.target, case.name) for case in second]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))


def test_target_filtering_is_exact() -> None:
    campaign = build_campaign(targets=("external-contact", "artifact-guard"))
    assert len(campaign) == 65
    assert {case.target for case in campaign} == {"external-contact", "artifact-guard"}


def test_scopeguard_segment_keeps_strict_120_case_gate() -> None:
    report = run_campaign(build_campaign(targets=("scopeguard",)))
    assert report.total == 120
    assert report.passed
    assert report.surprising_count == 0
    assert report.harness_exception_count == 0


def test_offense_first_contract_rejects_removed_and_explicitly_disabled_boundaries() -> None:
    results = _results_for(
        "offense-first",
        "baseline",
        "drop-third-party-authority",
        "drop-bounded-autonomy",
        "inject-disable-scopeguard",
        "inject-allow-any-host",
        "inject-unbounded-autonomy",
    )
    assert results["baseline"].allowed is True
    for name in (
        "drop-third-party-authority",
        "drop-bounded-autonomy",
        "inject-disable-scopeguard",
        "inject-allow-any-host",
        "inject-unbounded-autonomy",
    ):
        assert results[name].allowed is False
        assert results[name].surprising is False


def test_offense_first_validator_rejects_explicit_unrestricted_marker() -> None:
    errors = validate_offense_first_document(
        "Arena / synthetic / owned-or-explicitly-authorized lab\n"
        "所有者または明示的なテスト権限\n"
        "外部資産に対する認可境界\n"
        "Owner / BOSS が追加 scope を明示的に認可\n"
        "BOSS が与えた上限まで\n"
        "UNAUTHORIZED_EXTERNAL_EXECUTION=ALLOW\n"
    )
    assert "forbidden:unrestricted-external" in errors


def test_security_guard_contract_detects_gate_and_privilege_regressions() -> None:
    results = _results_for(
        "security-guard",
        "baseline",
        "drop-required-02",
        "drop-required-06",
        "inject-forbidden-01",
        "inject-forbidden-03",
        "inject-forbidden-06",
    )
    assert results["baseline"].allowed is True
    for name in (
        "drop-required-02",
        "drop-required-06",
        "inject-forbidden-01",
        "inject-forbidden-03",
        "inject-forbidden-06",
    ):
        assert results[name].allowed is False
        assert results[name].surprising is False


def test_security_guard_validator_rejects_empty_workflow() -> None:
    errors = validate_security_guard_workflow("")
    assert errors
    assert any(error.startswith("missing:") for error in errors)


def test_engagement_campaign_rejects_scope_and_type_confusion() -> None:
    results = _results_for(
        "engagement-json",
        "valid-window",
        "request-budget-max",
        "authorization-missing",
        "wildcard-host",
        "unknown-check",
        "destructive",
        "expired-window",
        "allow-http-string-false",
        "request-budget-string",
        "rps-bool",
    )
    assert results["valid-window"].allowed is True
    assert results["request-budget-max"].allowed is True
    for name in (
        "authorization-missing",
        "wildcard-host",
        "unknown-check",
        "destructive",
        "expired-window",
        "allow-http-string-false",
        "request-budget-string",
        "rps-bool",
    ):
        assert results[name].allowed is False
        assert results[name].surprising is False


def test_external_contact_blocks_before_fake_transport_for_core_rejections() -> None:
    results = _results_for(
        "external-contact",
        "unlisted-host",
        "plain-http-disabled",
        "userinfo-password",
        "delete-no-optin",
        "caller-host-header",
        "private-resolver-v4",
        "invalid-resolver-result",
    )
    for result in results.values():
        assert result.allowed is False
        assert result.side_effect_calls == 0
        assert result.surprising is False


def test_external_contact_valid_mutations_reach_only_fake_transport() -> None:
    results = _results_for(
        "external-contact",
        "https-get",
        "https-post-small-body",
        "https-delete-explicit",
    )
    for result in results.values():
        assert result.allowed is True
        assert result.side_effect_calls == 1
        assert result.surprising is False


def test_artifact_guard_is_exercised_as_real_subprocess() -> None:
    results = _results_for(
        "artifact-guard",
        "safe-html",
        "source-map-file",
        "openai-token",
        "slack-bot-token",
    )
    assert results["safe-html"].allowed is True
    for name in ("source-map-file", "openai-token", "slack-bot-token"):
        assert results[name].allowed is False
        assert results[name].surprising is False
    assert results["safe-html"].harness_exception_type is None


def test_autonomy_engine_inputs_are_bounded_and_real_package_is_exercised() -> None:
    results = _results_for(
        "autonomy-engine",
        "valid-default",
        "queue-roundtrip",
        "engine-seeds-bounded",
        "unknown-category",
        "matches-over-max",
        "authority-unknown",
        "status-unknown",
    )
    for name in ("valid-default", "queue-roundtrip", "engine-seeds-bounded"):
        assert results[name].allowed is True
        assert results[name].surprising is False
    for name in ("unknown-category", "matches-over-max", "authority-unknown", "status-unknown"):
        assert results[name].allowed is False
        assert results[name].surprising is False


def test_report_is_machine_readable_and_carries_v2_risk_breakdown() -> None:
    report = run_campaign(build_campaign(targets=("scopeguard", "offense-first")))
    payload = json.loads(report.to_json(indent=None))
    assert payload["schema"] == "senju-multiguard-adversary/v2"
    assert payload["total"] == 140
    assert payload["by_target"]["scopeguard"]["total"] == 120
    assert payload["by_target"]["offense-first"]["total"] == 20
    assert payload["risk_score"] == 0
    assert payload["side_effect_violation_count"] == 0
    assert len(payload["campaign_fingerprint"]) == 64


def test_full_300_case_campaign_is_surprise_free() -> None:
    report = run_campaign()
    assert report.total == 300
    assert report.passed
    assert report.surprising_count == 0
    assert report.harness_exception_count == 0
    assert report.side_effect_violation_count == 0
    assert report.risk_score == 0


def test_multiguard_paths_are_the_real_repository_guard_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = {
        repo_root / "senju" / "OFFENSE_FIRST.md": OFFENSE_FIRST_PATH,
        repo_root / ".github" / "workflows" / "security-guard.yml": SECURITY_GUARD_PATH,
        repo_root / "scripts" / "security" / "artifact_guard.py": ARTIFACT_GUARD_PATH,
    }
    for canonical, harness_path in expected.items():
        assert harness_path.resolve() == canonical.resolve()
        assert canonical.is_file()
        assert len(_sha256(canonical)) == 64


def test_multiguard_runtime_targets_are_real_package_classes() -> None:
    assert EngagementManifest.__module__ == "senju.authorized_assessment"
    assert ExternalContactClient.__module__ == "senju.external"
    assert AutonomyEngine.__module__ == "senju.autonomy.engine"

    repo_root = Path(__file__).resolve().parents[2]
    expected_sources = {
        EngagementManifest: repo_root / "senju" / "senju" / "authorized_assessment.py",
        ExternalContactClient: repo_root / "senju" / "senju" / "external.py",
        AutonomyEngine: repo_root / "senju" / "senju" / "autonomy" / "engine.py",
    }
    for cls, canonical in expected_sources.items():
        assert Path(inspect.getsourcefile(cls) or "").resolve() == canonical.resolve()


def test_requested_guard_stack_is_covered_by_real_campaign() -> None:
    requested = {
        "offense-first",
        "engagement-json",
        "external-contact",
        "security-guard",
        "artifact-guard",
        "autonomy-engine",
    }
    campaign = build_campaign(targets=tuple(sorted(requested)))
    assert {case.target for case in campaign} == requested

    report = run_campaign(campaign)
    assert report.passed
    assert report.side_effect_violation_count == 0
    for target in requested:
        assert report.by_target()[target]["total"] > 0
