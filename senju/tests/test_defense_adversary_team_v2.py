from __future__ import annotations

from pathlib import Path

from senju.defense_adversary_team_v2 import (
    audit_offense_text,
    audit_security_guard_text,
    probe_external_contact_v2,
    probe_scopeguard_v2,
    run_v2,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_v2_covers_every_requested_guard_layer() -> None:
    report = run_v2(_repo_root(), scope_cases=64, seed=7)
    layers = {finding.layer for finding in report.findings}
    assert {
        "scopeguard",
        "offense-first",
        "engagement-json",
        "external-contact",
        "security-guard-workflow",
        "artifact-guard",
        "autonomy-engine",
    } <= layers


def test_scopeguard_v2_is_large_and_deterministic() -> None:
    first = probe_scopeguard_v2(count=128, seed=99)
    second = probe_scopeguard_v2(count=128, seed=99)
    assert len(first) >= 128
    assert [(x.case, x.passed, x.detail) for x in first] == [
        (x.case, x.passed, x.detail) for x in second
    ]


def test_external_contact_probe_includes_authority_confusion_cases() -> None:
    names = {finding.case for finding in probe_external_contact_v2()}
    assert {
        "userinfo-host-confusion",
        "suffix-lookalike",
        "bad-port-range",
        "non-default-port",
    } <= names


def test_offense_contract_auditor_detects_boundary_removal() -> None:
    text = (
        "owned-or-explicitly-authorized lab\n"
        "外部第三者の資産\n"
        "所有者または明示的なテスト権限\n"
        "campaign scope\n"
    )
    assert audit_offense_text(text) == []
    assert audit_offense_text(text.replace("所有者または明示的なテスト権限", ""))


def test_security_guard_auditor_detects_high_risk_mutations() -> None:
    baseline = """permissions:\n  contents: read\n  pull_request:\n    branches: [main]\npersist-credentials: false\nBlock tracked secret files\nBlock obvious credential material in tracked source\nEnforce fail-closed workflow policy\nEnforce external-evidence reality gate\nBlock remote shell execution patterns\nBlock direct interpolation of untrusted event text\n"""
    assert audit_security_guard_text(baseline) == []
    assert audit_security_guard_text(baseline.replace("  pull_request:", "  pull_request_target:"))
    assert audit_security_guard_text(baseline.replace("contents: read", "contents: write"))
    assert audit_security_guard_text(baseline.replace("persist-credentials: false", "persist-credentials: true"))


def test_report_is_json_ready() -> None:
    report = run_v2(_repo_root(), scope_cases=8, seed=1)
    payload = report.to_dict()
    assert payload["schema"] == "senju-defense-adversary-suite/v2"
    assert payload["summary"]["checks"] == len(report.findings)
    assert isinstance(payload["summary"]["layers"], dict)
