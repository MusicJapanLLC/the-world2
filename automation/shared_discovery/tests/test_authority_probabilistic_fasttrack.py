from __future__ import annotations

import json
from pathlib import Path

from engine.authority_probabilistic_fasttrack import (
    BUCKET_SECONDS,
    EXTRA_REVIEW_PERCENT,
    FAST_TRACK_PERCENT,
    draw_for,
    extra_review_draw_for,
    run_probabilistic_fasttrack,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _bucket_with_fasttrack(host: str) -> int:
    for bucket in range(10000):
        if draw_for(host, bucket) < FAST_TRACK_PERCENT:
            return bucket
    raise AssertionError("expected a deterministic 5% hit")


def _bucket_with_secondary_crosscheck(host: str) -> int:
    for bucket in range(100000):
        if (
            draw_for(host, bucket) < FAST_TRACK_PERCENT
            and extra_review_draw_for(host, bucket) < EXTRA_REVIEW_PERCENT
        ):
            return bucket
    raise AssertionError("expected a deterministic fast-track plus secondary review hit")


def test_persistent_candidate_can_receive_real_five_percent_authority_transition_fasttrack(tmp_path: Path) -> None:
    host = "candidate.example"
    bucket = _bucket_with_fasttrack(host)
    _write(
        tmp_path / "authority_candidate_council.json",
        {"dossiers": [{"host": host, "url": f"https://{host}/", "status": "unknown_root_evidence_search", "terminal_stop": False}]},
    )
    result = run_probabilistic_fasttrack(tmp_path, now=bucket * BUCKET_SECONDS)
    assert result["probability_percent_per_bucket"] == 5
    assert result["extra_review_percent_on_fasttrack"] == 10
    assert result["fast_track_count"] == 1
    assert result["authority_transition_requests_created"] == 1
    queue = json.loads((tmp_path / "authority_priority_review_queue.json").read_text())
    request = queue["requests"][0]
    assert request["priority"] == 100
    assert request["threshold_percent"] == 5
    assert request["authority_transition_requested"] is True
    assert request["authority_effect"] == "formal_authority_transition_request_requires_existing_approval"
    assert set(request["shared_with"]) == {"META", "X", "SENJU", "CHILD", "PR-ARMY"}
    assert "submit_authority_transition_request_to_existing_review" in request["autonomous_next_actions"]
    assert "generate_owner_verification_packet" in request["autonomous_next_actions"]
    assert request["may_self_mint_new_root"] is False
    assert request["may_override_hard_deny"] is False


def test_ten_percent_of_fasttracks_can_get_secondary_independent_crosscheck(tmp_path: Path) -> None:
    host = "crosscheck.example"
    bucket = _bucket_with_secondary_crosscheck(host)
    _write(
        tmp_path / "authority_candidate_council.json",
        {"dossiers": [{"host": host, "url": f"https://{host}/", "status": "unknown_root_evidence_search", "terminal_stop": False}]},
    )
    result = run_probabilistic_fasttrack(tmp_path, now=bucket * BUCKET_SECONDS)
    assert result["fast_track_count"] == 1
    assert result["secondary_review_crosscheck_count"] == 1
    queue = json.loads((tmp_path / "authority_priority_review_queue.json").read_text())
    request = queue["requests"][0]
    assert request["secondary_review_crosscheck"] is True
    assert request["secondary_review_threshold_percent"] == 10
    assert "request_secondary_independent_reviewer_crosscheck" in request["autonomous_next_actions"]


def test_terminal_stop_never_uses_lottery_fasttrack(tmp_path: Path) -> None:
    host = "terminal.example"
    bucket = _bucket_with_fasttrack(host)
    _write(
        tmp_path / "authority_candidate_council.json",
        {"dossiers": [{"host": host, "status": "terminal_stop_requires_owner_reactivation", "terminal_stop": True}]},
    )
    result = run_probabilistic_fasttrack(tmp_path, now=bucket * BUCKET_SECONDS)
    assert result["evaluated_candidates"] == 0
    assert result["fast_track_count"] == 0
    assert result["terminal_stop_lottery_bypass"] is False


def test_new_bucket_gives_candidate_a_new_draw(tmp_path: Path) -> None:
    host = "persistent.example"
    _write(
        tmp_path / "authority_candidate_council.json",
        {"dossiers": [{"host": host, "status": "unknown_root_evidence_search", "terminal_stop": False}]},
    )
    first = draw_for(host, 10)
    second = draw_for(host, 11)
    assert first == draw_for(host, 10)
    assert 0 <= first < 100
    assert 0 <= second < 100
    result = run_probabilistic_fasttrack(tmp_path, now=11 * BUCKET_SECONDS)
    assert result["persistent_candidates_receive_new_chance_each_bucket"] is True
    assert result["probability_percent_per_bucket"] == 5
    assert result["extra_review_percent_on_fasttrack"] == 10
    assert result["new_root_self_mint"] is False
    assert result["hard_deny_identity_bypass"] is False
