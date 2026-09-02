from __future__ import annotations

import json
from pathlib import Path

from engine.authority_signal_bridge import run_authority_signal_bridge


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _candidate_state(state: Path, host: str = "candidate.example") -> None:
    _write(
        state / "discovery_candidates.json",
        {"candidates": [{"host": host, "url": f"https://{host}/", "decision": "candidate_only"}]},
    )


def _strong_intent(state: Path, host: str = "candidate.example", score: float = 0.9) -> None:
    _write(
        state / "human_intent_decisions.json",
        {
            "decisions": [
                {
                    "host": host,
                    "url": f"https://{host}/",
                    "confidence": 0.95,
                    "likely_owner_intent": True,
                    "reasons": [f"prior_similarity:{score:.2f}"],
                }
            ]
        },
    )
    _write(state / "human_intent_signals.json", {"similarity_by_host": {host: score}})


def _consensus(state: Path, host: str = "candidate.example") -> None:
    ballots = [
        {"actor": actor, "recommendation": "route_root_candidate_to_review"}
        for actor in ("META", "X", "SENJU", "CHILD", "PR-ARMY")
    ]
    _write(state / "authority_candidate_council.json", {"dossiers": [{"host": host, "ballots": ballots}]})


def test_discovery_always_enters_authority_pipeline(tmp_path: Path) -> None:
    _candidate_state(tmp_path)
    result = run_authority_signal_bridge(tmp_path, now=100)
    records = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"]

    assert result["connected"] is True
    assert result["candidate_count"] == 1
    assert records[0]["authority_candidate"] is True
    assert records[0]["signals"]["discovery"] is True
    assert records[0]["provisional_authority"] is False
    assert records[0]["live_authority_connected"] is False


def test_similarity_promotes_candidate_to_provisional_authority(tmp_path: Path) -> None:
    _candidate_state(tmp_path)
    _strong_intent(tmp_path, score=0.72)
    result = run_authority_signal_bridge(tmp_path, now=100)
    record = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"][0]

    assert result["provisional_authority_count"] == 1
    assert record["signals"]["similarity_authorizing_signal"] is True
    assert record["provisional_authority"] is True
    assert record["auto_apply_ready"] is False
    assert record["authority_effect"] == "provisional_only"


def test_ai_consensus_promotes_candidate_to_provisional_authority(tmp_path: Path) -> None:
    _candidate_state(tmp_path)
    _consensus(tmp_path)
    result = run_authority_signal_bridge(tmp_path, now=100)
    record = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"][0]

    assert result["provisional_authority_count"] == 1
    assert record["signals"]["ai_consensus"] is True
    assert record["signals"]["ai_consensus_positive_votes"] == 5
    assert record["provisional_authority"] is True


def test_all_three_signals_become_auto_apply_ready_without_new_live_root(tmp_path: Path) -> None:
    _candidate_state(tmp_path)
    _strong_intent(tmp_path, score=0.91)
    _consensus(tmp_path)

    result = run_authority_signal_bridge(tmp_path, now=100)
    record = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"][0]
    queue = json.loads((tmp_path / "signal_authority_activation_queue.json").read_text())["requests"]

    assert result["auto_apply_ready_count"] == 1
    assert result["live_authority_connected_count"] == 0
    assert result["no_reprompt_for_auto_apply_ready"] is True
    assert result["new_unrelated_live_root_from_signals_alone"] is False
    assert record["signal_count"] == 3
    assert record["auto_apply_ready"] is True
    assert record["live_authority_connected"] is False
    assert queue[0]["status"] == "auto_apply_ready"
    assert queue[0]["apply_without_reprompt"] is True
    assert queue[0]["apply_requires_existing_or_independent_owner_authority"] is True


def test_signal_authority_connects_live_inside_existing_owner_envelope(tmp_path: Path) -> None:
    host = "owned.example"
    _candidate_state(tmp_path, host)
    _strong_intent(tmp_path, host, score=0.95)
    _consensus(tmp_path, host)
    _write(
        tmp_path / "discovery_authorized.json",
        {
            "hosts": {
                host: {
                    "host": host,
                    "authorization_basis": "trusted_root",
                    "effect": "read_only",
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                }
            }
        },
    )

    result = run_authority_signal_bridge(tmp_path, now=100)
    record = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"][0]

    assert result["live_authority_connected_count"] == 1
    assert record["inside_existing_owner_envelope"] is True
    assert record["live_authority_connected"] is True
    assert record["auto_execute_allowed"] is True
    assert record["authority_effect"] == "reuse_existing_owner_envelope"
    assert record["next_step"] == "execute_with_existing_owner_authority"


def test_provisional_authority_is_persistent_and_reconsidered(tmp_path: Path) -> None:
    _candidate_state(tmp_path)
    _strong_intent(tmp_path, score=0.7)
    first = run_authority_signal_bridge(tmp_path, now=100)
    second = run_authority_signal_bridge(tmp_path, now=200)
    record = json.loads((tmp_path / "provisional_authorities.json").read_text())["records"][0]

    assert first["persistent_reconsideration"] is True
    assert second["persistent_reconsideration"] is True
    assert record["first_seen"] == 100
    assert record["last_seen"] == 200
    assert record["reconsideration_count"] == 2
