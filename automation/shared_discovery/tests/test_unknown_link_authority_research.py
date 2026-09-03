from __future__ import annotations

import json

from engine.unknown_link_authority_research import run_unknown_link_authority_research


def _write_opportunity(state, *, confidence=0.9):
    (state / "owner_authority_opportunity_queue.json").write_text(
        json.dumps(
            {
                "opportunities": [
                    {
                        "host": "unknown.example.net",
                        "url": "https://unknown.example.net/api",
                        "signals": {"intent_confidence": confidence},
                        "status": "searching",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_loop_persists_attempts_and_rotates_research_strategy(tmp_path):
    _write_opportunity(tmp_path, confidence=0.7)
    first = run_unknown_link_authority_research(tmp_path, chaos_rate=0.0)
    first_state = json.loads((tmp_path / "unknown_link_authority_research_state.json").read_text())
    first_row = first_state["opportunities"][0]

    second = run_unknown_link_authority_research(tmp_path, chaos_rate=0.0)
    second_state = json.loads((tmp_path / "unknown_link_authority_research_state.json").read_text())
    second_row = second_state["opportunities"][0]

    assert first["closed_loop"] is True
    assert second["closed_loop"] is True
    assert first_row["attempt_count"] == 1
    assert second_row["attempt_count"] == 2
    assert first_row["strategy"] != second_row["strategy"]
    assert second_row["persistent_until_resolved"] is True


def test_pr_army_shared_evidence_is_fused_into_research(tmp_path):
    _write_opportunity(tmp_path, confidence=0.9)
    (tmp_path / "authority_improvement_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "source": "PR-ARMY",
                        "finding": "unknown.example.net appeared in PR #999 evidence",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_unknown_link_authority_research(tmp_path, chaos_rate=0.0)
    state = json.loads((tmp_path / "unknown_link_authority_research_state.json").read_text())
    row = state["opportunities"][0]

    assert row["pr_army_evidence_refs"]
    assert "PR-ARMY" in row["shared_with"]
    assert result["review_ready_count"] == 0 or result["review_ready_count"] == 1


def test_high_research_score_routes_to_meta_x_senju_pr_army_review(tmp_path):
    _write_opportunity(tmp_path, confidence=1.0)
    (tmp_path / "authority_improvement_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"evidence": "unknown.example.net PR evidence A"},
                    {"evidence": "unknown.example.net PR evidence B"},
                    {"evidence": "unknown.example.net PR evidence C"},
                    {"evidence": "unknown.example.net PR evidence D"},
                ]
            }
        ),
        encoding="utf-8",
    )

    # Repeated research is allowed to increase review readiness without changing authority.
    for _ in range(3):
        result = run_unknown_link_authority_research(tmp_path, chaos_rate=0.0)

    requests = json.loads((tmp_path / "unknown_link_council_review_requests.json").read_text())
    assert result["review_ready_count"] == 1
    assert requests["request_count"] == 1
    request = requests["requests"][0]
    assert request["members"] == ["META", "X", "SENJU", "PR-ARMY"]
    assert request["quorum_target"] == 3
    assert request["authority_effect"] == "none"
    assert request["execution_effect"] == "none"
    assert request["may_mint_new_authority"] is False
    assert request["may_execute_external_post"] is False


def test_random_synthetic_false_report_is_explicitly_labeled_and_isolated(tmp_path):
    _write_opportunity(tmp_path, confidence=1.0)
    result = run_unknown_link_authority_research(
        tmp_path,
        chaos_rate=0.25,
        random_value=lambda: 0.0,
    )
    reports = json.loads((tmp_path / "synthetic_chaos_reports.json").read_text())

    assert result["synthetic_report_count"] == 1
    assert result["synthetic_reports_truth_labeled"] is True
    report = reports["reports"][0]
    assert report["synthetic"] is True
    assert report["known_false"] is True
    assert report["truth_label"] == "synthetic_known_false"
    assert report["excluded_from_scoring"] is True
    assert report["excluded_from_authorization"] is True
    assert report["excluded_from_execution"] is True


def test_synthetic_report_cannot_change_authority_or_execute_post(tmp_path):
    _write_opportunity(tmp_path, confidence=1.0)
    result = run_unknown_link_authority_research(
        tmp_path,
        chaos_rate=0.25,
        random_value=lambda: 0.0,
    )
    state = json.loads((tmp_path / "unknown_link_authority_research_state.json").read_text())

    assert result["new_authority_minted"] is False
    assert result["external_post_executed"] is False
    assert state["new_authority_minted"] is False
    assert state["external_post_executed"] is False
    assert state["opportunities"][0]["authority_effect"] == "none"
    assert state["opportunities"][0]["execution_effect"] == "none"


def test_duplicate_candidate_sources_do_not_duplicate_research_rows(tmp_path):
    _write_opportunity(tmp_path, confidence=0.8)
    (tmp_path / "authority_opportunity_queue.json").write_text(
        json.dumps(
            {
                "opportunities": [
                    {
                        "host": "unknown.example.net",
                        "url": "https://unknown.example.net/api",
                        "confidence": 0.8,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = run_unknown_link_authority_research(tmp_path, chaos_rate=0.0)
    assert result["opportunity_count"] == 1
