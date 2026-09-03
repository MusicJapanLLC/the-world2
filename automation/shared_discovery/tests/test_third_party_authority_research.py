from __future__ import annotations

import json
from pathlib import Path

from engine.third_party_authority_research import run_third_party_authority_research_loop


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    host = "outside.example"
    url = f"https://{host}/research"
    _write(
        state / "human_intent_decisions.json",
        {
            "decisions": [
                {
                    "host": host,
                    "url": url,
                    "confidence": 0.88,
                    "likely_owner_intent": True,
                    "reasons": [
                        "owner_context",
                        "prior_similarity:0.92",
                        "prior_explicit_approval_exists",
                    ],
                }
            ]
        },
    )
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "host": host,
                    "url": url,
                    "decision": "candidate_only",
                    "reason": "outside_authorized_scope",
                }
            ]
        },
    )
    _write(state / "discovery_authorized.json", {"hosts": {}})
    return state


def test_research_latitude_increases_hypothesis_freedom_without_authority(tmp_path: Path) -> None:
    state = _state(tmp_path)
    result = run_third_party_authority_research_loop(state)
    doc = json.loads((state / "third_party_authority_research.json").read_text(encoding="utf-8"))
    row = doc["research_items"][0]

    assert result["research_latitude"] == 0.45
    assert row["research_latitude"] == 0.45
    assert row["hypotheses_allowed"] is True
    assert row["research_score"] > 0.45
    assert row["research_score_is_authority"] is False
    assert row["authority_effect"] == "none"
    assert row["may_mint_owner_authority"] is False
    assert row["may_promote_candidate"] is False
    assert row["may_enqueue_external_action"] is False
    assert row["may_contact_third_party_host"] is False


def test_research_is_persistent_and_rotates_non_authoritative_lens(tmp_path: Path) -> None:
    state = _state(tmp_path)
    run_third_party_authority_research_loop(state)
    first = json.loads((state / "third_party_authority_research.json").read_text(encoding="utf-8"))
    first_row = first["research_items"][0]
    first_seen = first_row["first_seen_at"]
    first_lens = first_row["research_agenda"][-1]

    second_result = run_third_party_authority_research_loop(state)
    second = json.loads((state / "third_party_authority_research.json").read_text(encoding="utf-8"))
    second_row = second["research_items"][0]

    assert second_result["total_attempt_count"] == 2
    assert second_row["attempt_count"] == 2
    assert second_row["first_seen_at"] == first_seen
    assert second_row["research_agenda"][-1] != first_lens
    assert second_row["status"] == "researching"
    assert second_row["persistent_research"] is True


def test_counterevidence_and_missing_authorization_are_part_of_agenda(tmp_path: Path) -> None:
    state = _state(tmp_path)
    run_third_party_authority_research_loop(state)
    row = json.loads((state / "third_party_authority_research.json").read_text(encoding="utf-8"))["research_items"][0]

    assert row["counterevidence_required"] is True
    assert "identify_missing_explicit_authorization_evidence" in row["research_agenda"]
    assert "prepare_owner_authorization_request_if_needed" in row["research_agenda"]
    assert "search_for_counterevidence_in_existing_state" in row["research_agenda"]
    assert "analyze_similarity_without_treating_similarity_as_authority" in row["research_agenda"]


def test_live_authority_resolves_research_but_research_does_not_create_it(tmp_path: Path) -> None:
    state = _state(tmp_path)
    host = "outside.example"
    _write(
        state / "discovery_authorized.json",
        {
            "hosts": {
                host: {
                    "authorization_reference": "review:outside-example",
                    "expires_at": 4_000_000_000,
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                }
            }
        },
    )

    result = run_third_party_authority_research_loop(state)
    row = json.loads((state / "third_party_authority_research.json").read_text(encoding="utf-8"))["research_items"][0]

    assert result["resolved_count"] == 1
    assert row["status"] == "resolved_authority_present"
    assert row["live_authorization_reference"] == "review:outside-example"
    assert row["persistent_research"] is False
    assert row["authority_effect"] == "none"
    assert result["new_owner_authority_from_research"] is False
