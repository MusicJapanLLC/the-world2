from __future__ import annotations

import json
from pathlib import Path

from engine.reviewed_root_authority_negotiation import run_reviewed_root_authority_negotiation


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_admitted_root_case_enters_existing_formal_review_surface(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "authority_opportunity_queue.json", {
        "opportunities": [{
            "host": "root-review.example",
            "request_id": "root-review-1",
            "reason": "candidate from negotiation AI",
            "score": 80,
            "authority_effect": "none",
        }]
    })
    result = run_reviewed_root_authority_negotiation(state, repo_root=tmp_path, now=1000)
    assert result["intake_review"]["admitted_count"] == 1
    assert result["formal_discussion_started_case_count"] == 1
    assert result["candidate_count"] == 1
    assert result["council_review_packet_count"] == 1
    assert result["new_root_created"] is False
    assert result["intake_authority_effect"] == "none"
    assert (state / "owner_root_authority_review_packets.json").exists()


def test_held_root_case_never_reaches_formal_review_surface(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "authority_opportunity_queue.json", {
        "opportunities": [{
            "host": "held-root.example",
            "request_id": "root-held-1",
            "reason": "unsafe packet",
            "score": 95,
            "authority_effect": "already_granted",
        }]
    })
    result = run_reviewed_root_authority_negotiation(state, repo_root=tmp_path, now=1000)
    assert result["intake_review"]["held_count"] == 1
    assert result["formal_discussion_started_case_count"] == 0
    assert result["candidate_count"] == 0
    packets = json.loads((state / "owner_root_authority_review_packets.json").read_text())
    assert packets["packets"] == []
