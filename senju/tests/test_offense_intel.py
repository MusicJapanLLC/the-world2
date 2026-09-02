from __future__ import annotations

from senju.offense_intel import build_bundle, report_to_target


def _report(findings):
    return {
        "schema": "senju-authorized-pentest-report/v1",
        "scope_id": "owned-ci-target",
        "target": "https://owned.example/",
        "findings": findings,
        "requests_used": 4,
        "receipts": [],
        "boundaries": {
            "credential_guessing": False,
            "auth_bypass": False,
            "exploit_delivery": False,
            "persistence": False,
            "destructive_requests": False,
            "lateral_movement": False,
            "methods": ["GET", "HEAD", "OPTIONS"],
        },
    }


def test_high_cors_finding_becomes_csrf_red_pressure():
    target, genome, source_map = report_to_target(_report([
        {
            "severity": "high",
            "key": "cors-origin-reflection",
            "title": "CORS reflects arbitrary origin",
            "evidence": "probe origin reflected",
            "remediation": "allowlist origins",
        }
    ]))
    assert target.ref == "sim://pentest-intel/owned-ci-target"
    assert target.surfaces()[0].vuln_class == "csrf"
    assert genome.focus["csrf"] >= 0.9
    assert source_map[0]["interpretation"] == "measured-observation-to-synthetic-red-pressure"


def test_no_findings_does_not_stop_red_novelty_hunt():
    target, genome, source_map = report_to_target(_report([]))
    classes = {surface.vuln_class for surface in target.surfaces()}
    assert {"auth_bypass", "idor", "ssrf", "race_condition", "misconfig"}.issubset(classes)
    assert all(item["interpretation"] == "no-known-finding-novelty-hunt" for item in source_map)
    assert genome.focus["ssrf"] > 0


def test_bundle_runs_campaigns_without_widening_authority():
    bundle = build_bundle([
        _report([
            {"severity": "medium", "key": "csp-missing"},
            {"severity": "high", "key": "unknown-route-success"},
        ])
    ], cycles=5, seed=17)
    assert bundle["schema"] == "senju-pentest-to-red/v1"
    assert bundle["doctrine"] == "REAL_OBSERVATION_TO_RED_RESEARCH"
    assert bundle["network_io"] is False
    assert bundle["exploit_payloads_emitted"] is False
    assert bundle["source_authority_widened"] is False
    assert bundle["source_reports"] == 1
    assert len(bundle["reports"][0]["campaigns"]) == 5
    assert bundle["reports"][0]["synthetic_target_ref"].startswith("sim://pentest-intel/")


def test_findings_raise_multiple_red_focus_classes():
    _, genome, _ = report_to_target(_report([
        {"severity": "high", "key": "cookie-httponly-missing"},
        {"severity": "medium", "key": "dangerous-methods-advertised"},
        {"severity": "low", "key": "banner-server"},
    ]))
    assert genome.focus["auth_bypass"] > genome.focus["misconfig"] > genome.focus["secrets_exposure"]
