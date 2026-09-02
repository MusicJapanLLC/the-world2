from __future__ import annotations

import json
from pathlib import Path

from engine.authority_collaboration_bus import build_authority_collaboration_bus


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_bus_fuses_root_and_promotion_feedback_into_shared_agent_inboxes(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    root = tmp_path / "root"
    promotion = tmp_path / "promotion"

    _write(root / "root_authority_negotiation_state.json", {
        "candidates": [
            {
                "candidate_id": "root-1",
                "host": "root.example.com",
                "readiness_score": 88,
                "status": "persistent_root_authority_negotiation",
                "terminal_stop": False,
                "source_refs": ["source-a"],
                "reasons": ["root evidence"],
            }
        ]
    })
    _write(promotion / "promotion_packets.json", {
        "packets": [
            {
                "proposal_id": "proposal-1",
                "host": "promotion.example.com",
                "status": "READY_FOR_STANDING_AUTHORIZATION",
                "requested_methods": ["GET", "HEAD"],
                "average_yes_confidence": 94,
                "proof_type": "owner_verified_domain",
                "proof_ref": "proof-1",
                "council_unanimous": True,
                "standing_authorization_match": False,
                "next_action": "collect exact-host standing authorization evidence",
            }
        ]
    })
    _write(promotion / "execution_ready.json", {
        "records": [
            {
                "proposal_id": "proposal-ready",
                "host": "ready.example.com",
                "status": "AUTHORIZED_EXECUTION_READY",
                "covered_methods": ["GET", "HEAD"],
                "average_yes_confidence": 99,
                "proof_type": "existing_standing_authorization",
                "proof_ref": "standing:ready.example.com",
                "council_unanimous": True,
                "next_action": "handoff authorized work",
            }
        ]
    })
    _write(promotion / "last_promotion_cycle.json", {"proposal_count": 2})

    result = build_authority_collaboration_bus(
        bus,
        root_state_dir=root,
        promotion_state_dir=promotion,
        now=123,
    )
    assert result["closed_loop"] is True
    assert result["bidirectional_exchange"] is True
    assert result["promotion_feedback_reingested"] is True
    assert result["root_candidate_count"] == 1
    assert result["promotion_candidate_count"] == 1
    assert result["authority_effect"] == "none"

    evidence = json.loads((bus / "negotiation_evidence_bundle.json").read_text())
    assert set(evidence["hosts"]) == {
        "root.example.com",
        "promotion.example.com",
        "ready.example.com",
    }
    assert evidence["hosts"]["promotion.example.com"]["proof_types"] == ["owner_verified_domain"]
    assert evidence["hosts"]["ready.example.com"]["execution_ready"] is True
    assert evidence["hosts"]["ready.example.com"]["standing_authorization_match"] is True

    inboxes = json.loads((bus / "negotiation_agent_inboxes.json").read_text())
    assert set(inboxes["agents"]) == {"META", "X", "SENJU", "PR-ARMY", "CHILD", "AI"}
    for actor in inboxes["agents"]:
        tasks = inboxes["inboxes"][actor]
        assert {task["host"] for task in tasks} == {
            "root.example.com",
            "promotion.example.com",
            "ready.example.com",
        }
    promotion_task = next(
        task for task in inboxes["inboxes"]["META"]
        if task["host"] == "promotion.example.com"
    )
    assert promotion_task["kind"] == "standing_authorization_evidence"
    ready_task = next(
        task for task in inboxes["inboxes"]["SENJU"]
        if task["host"] == "ready.example.com"
    )
    assert ready_task["kind"] == "execution_handoff"

    protocol = json.loads((bus / "negotiation_coordination_protocol.json").read_text())
    assert "read_shared_negotiation_evidence" in protocol["capabilities"]["all_agents"]
    assert "verify_execution_handoff" in protocol["capabilities"]["SENJU"]
    assert protocol["new_unrelated_authority_mint"] is False


def test_terminal_feedback_is_sticky_and_removes_existing_opportunity(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    promotion = tmp_path / "promotion"
    _write(bus / "authority_opportunity_queue.json", {
        "opportunities": [
            {
                "host": "blocked.example.com",
                "priority": 90,
                "confidence": 0.9,
                "source": "existing",
            }
        ]
    })
    _write(promotion / "promotion_packets.json", {
        "packets": [
            {
                "proposal_id": "blocked-1",
                "host": "blocked.example.com",
                "status": "BLOCKED_TERMINAL",
                "hard_deny": True,
            }
        ]
    })
    _write(promotion / "execution_ready.json", {"records": []})
    _write(promotion / "last_promotion_cycle.json", {})

    build_authority_collaboration_bus(bus, promotion_state_dir=promotion, now=456)
    queue = json.loads((bus / "authority_opportunity_queue.json").read_text())
    assert queue["opportunities"] == []
    evidence = json.loads((bus / "negotiation_evidence_bundle.json").read_text())
    assert evidence["hosts"]["blocked.example.com"]["terminal_stop"] is True
