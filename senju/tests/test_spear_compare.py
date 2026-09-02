from senju.spear_compare import compare_summaries


def summary(host="example.com", findings=None, receipts=None):
    return {
        "schema": "senju-spear-continuous-summary/v1",
        "targets": [
            {
                "target_host": host,
                "findings": findings or [],
                "receipts": receipts or [],
            }
        ],
    }


def finding(key, severity="medium", title=None):
    return {"key": key, "severity": severity, "title": title or key}


def receipt(check, status=200, sha="aaa"):
    return {"check": check, "status": status, "response_sha256": sha}


def test_first_run_creates_baseline() -> None:
    current = summary(findings=[finding("csp-missing")])
    diff = compare_summaries(current, None)
    assert diff["baseline_present"] is False
    assert diff["counts"]["new"] == 1
    assert diff["risk_direction"] == "baseline_created"


def test_compare_tracks_new_resolved_and_persisting() -> None:
    previous = summary(
        findings=[finding("csp-missing"), finding("hsts-missing", "high")]
    )
    current = summary(
        findings=[finding("csp-missing"), finding("cors-origin-reflection", "high")]
    )
    diff = compare_summaries(current, previous)
    assert {x["key"] for x in diff["new_findings"]} == {"cors-origin-reflection"}
    assert {x["key"] for x in diff["resolved_findings"]} == {"hsts-missing"}
    assert {x["key"] for x in diff["persisting_findings"]} == {"csp-missing"}


def test_compare_tracks_severity_and_response_changes() -> None:
    previous = summary(
        findings=[finding("cors", "medium")],
        receipts=[receipt("root", 200, "aaa")],
    )
    current = summary(
        findings=[finding("cors", "high")],
        receipts=[receipt("root", 302, "bbb")],
    )
    diff = compare_summaries(current, previous)
    assert diff["counts"]["severity_up"] == 1
    assert diff["severity_changes"][0]["direction"] == "up"
    assert diff["counts"]["response_changed"] == 1
    change = diff["response_changes"][0]
    assert change["status_changed"] is True
    assert change["body_fingerprint_changed"] is True
    assert diff["risk_direction"] == "worse"


def test_resolving_high_finding_moves_risk_better() -> None:
    previous = summary(findings=[finding("cors", "high")])
    current = summary(findings=[])
    diff = compare_summaries(current, previous)
    assert diff["counts"]["resolved"] == 1
    assert diff["risk_direction"] == "better"
