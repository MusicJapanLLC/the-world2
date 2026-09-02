from __future__ import annotations

import pytest

from scripts.authorized_range_to_agency import AgencyBridgeError, convert_report


HOST = "kabeya-authorized-test-range.onrender.com"


def report(**overrides):
    data = {
        "schema": "senju-authorized-range-closed-loop/v2",
        "exact_host": HOST,
        "same_origin_only": True,
        "destructive": False,
        "request_count": 75,
        "pages_observed": 15,
        "blocked_out_of_scope": 0,
        "cycles": [
            {
                "cycle": 3,
                "probe_ranking_next": [
                    "reflection_canary",
                    "method_surface",
                    "error_differential",
                    "content_map",
                ],
            }
        ],
        "scheduler": {"reflection_canary": {"attempts": 15, "new_findings": 1}},
        "findings": [
            {
                "fingerprint": "abc123",
                "category": "input_reflection",
                "url": f"https://{HOST}/search",
                "severity": "info",
                "confidence": 0.85,
                "evidence": {"parameter": "senju_probe"},
                "observations": 2,
                "status": "confirmed",
            },
            {
                "fingerprint": "def456",
                "category": "state_form_without_visible_csrf_hint",
                "url": f"https://{HOST}/form",
                "severity": "low",
                "confidence": 0.45,
                "evidence": {"method": "POST"},
                "observations": 1,
                "status": "new",
            },
        ],
        "finding_shares": [
            {
                "fingerprint": "abc123",
                "probe_family": "reflection_canary",
            },
            {
                "fingerprint": "def456",
                "probe_family": "content_map",
            },
        ],
    }
    data.update(overrides)
    return data


def test_bridge_maps_live_report_into_agency_owned_range_contract() -> None:
    packet = convert_report(report())
    assert packet["schema"] == "senju-owned-range-active/v2"
    assert packet["authorized_host"] == HOST
    assert packet["request_count"] == 75
    assert packet["pages_discovered"] == 15
    assert packet["write_attempts"] == 0
    assert packet["counterexample_count"] == 2
    assert packet["forms_discovered"] == 1
    assert len(packet["digest"]) == 24
    assert packet["evolution"]["next_family_ranking"][0] == "reflection_canary"


def test_bridge_preserves_probe_family_and_confirmation_context() -> None:
    packet = convert_report(report())
    by_kind = {row["kind"]: row for row in packet["counterexamples"]}
    reflection = by_kind["input_reflection"]
    assert reflection["probe"] == "reflection_canary"
    assert reflection["outcome"] == "confirmed"
    assert reflection["observations"] == 2
    assert reflection["fingerprint"] == "abc123"


def test_bridge_rejects_non_same_origin_or_destructive_reports() -> None:
    with pytest.raises(AgencyBridgeError, match="same-origin-only"):
        convert_report(report(same_origin_only=False))
    with pytest.raises(AgencyBridgeError, match="non-destructive"):
        convert_report(report(destructive=True))
