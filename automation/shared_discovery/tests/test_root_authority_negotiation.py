from __future__ import annotations

import json
from pathlib import Path

from engine.authority_approval_constitution import CANONICAL_FLOW_ID, CONSTITUTION_ID
from engine.root_authority_negotiation import AGENTS, NEGOTIATION_INTENSITY, TACTICS, run_root_authority_negotiation


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_candidate(state: Path, host: str = "new.example.com", **extra: object) -> None:
    row = {
        "host": host,
        "url": f"https://{host}/",
        "reason": "candidate needs broader authority review",
        "confidence": 0.8,
        **extra,
    }
    _write(state / "owner_authority_opportunity_queue.json", {"opportunities": [row]})


def _approve_by_council(state: Path, host: str) -> None:
    _write(state / "root_authority_council_decisions.json", {
        "decisions": [{
            "decision_id": f"council:{host}",
            "host": host,
            "approved": True,
            "approved_by": ["META", "X", "SENJU"],
            "constitution_id": CONSTITUTION_ID,
            "canonical_flow_id": CANONICAL_FLOW_ID,
        }]
    })


def test_four_agents_generate_28_tasks_and_attempts_persist(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_candidate(state)

    first = run_root_authority_negotiation(state, repo_root=tmp_path, now=100)
    assert first["agents"] == list(AGENTS)
    assert first["negotiation_intensity"] == NEGOTIATION_INTENSITY == 70
    assert first["task_count"] == len(AGENTS) * len(TACTICS) == 28
    assert first["META_X_SENJU_primary_review_is_first"] is True
    assert first["secondary_owner_or_standing_evidence_rank"] == 3
    assert first["unlisted_approval_flows_excluded"] is True
    assert first["new_root_created"] is False

    doc = json.loads((state / "root_authority_negotiation_state.json").read_text())
    candidate = doc["candidates"][0]
    assert candidate["attempt_count"] == 1
    assert candidate["status"] == "awaiting_META_X_SENJU_primary_review"
    assert candidate["readiness_ignores_secondary_owner_or_standing_evidence"] is True

    second = run_root_authority_negotiation(state, repo_root=tmp_path, now=200)
    assert second["task_count"] == 28
    doc = json.loads((state / "root_authority_negotiation_state.json").read_text())
    assert doc["candidates"][0]["attempt_count"] == 2


def test_every_active_candidate_enters_council_primary_review(tmp_path: Path) -> None:
    state = tmp_path / "state"
    opportunities = [
        {
            "host": f"candidate-{i}.example.com",
            "url": f"https://candidate-{i}.example.com/",
            "confidence": (i + 1) / 10,
        }
        for i in range(10)
    ]
    _write(state / "owner_authority_opportunity_queue.json", {"opportunities": opportunities})

    result = run_root_authority_negotiation(state, repo_root=tmp_path, now=100)
    assert result["active_candidate_count"] == 10
    assert result["council_review_packet_count"] == 10
    packets = json.loads((state / "owner_root_authority_review_packets.json").read_text())
    assert len(packets["packets"]) == 10
    assert all(packet["constitution_id"] == CONSTITUTION_ID for packet in packets["packets"])
    assert all(packet["canonical_flow_id"] == CANONICAL_FLOW_ID for packet in packets["packets"])
    assert all(packet["required_approvers"] == ["META", "X", "SENJU"] for packet in packets["packets"])
    assert all(packet["approval_stage"] == "executive_council_primary_review" for packet in packets["packets"])


def test_owner_evidence_alone_cannot_skip_council_primary_review(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_candidate(state, host="owned.example.com")
    _write(state / "owner_scope_expansion_evidence.json", {
        "evidence": [{
            "host": "owned.example.com",
            "proof_type": "owner_verified_domain",
            "proof_ref": "dns-proof:abc123",
            "verified": True,
            "revoked": False,
        }]
    })

    result = run_root_authority_negotiation(state, repo_root=tmp_path, now=100)
    assert result["existing_owner_activation_handoff_count"] == 0

    state_doc = json.loads((state / "root_authority_negotiation_state.json").read_text())
    candidate = state_doc["candidates"][0]
    assert candidate["status"] == "awaiting_META_X_SENJU_primary_review"
    assert candidate["secondary_validation"]["present"] is True
    assert candidate["secondary_validation"]["rank"] == 3
    assert candidate["secondary_validation"]["may_admit_candidate"] is False
    assert candidate["secondary_validation"]["may_raise_review_priority"] is False

    signals = json.loads((state / "owner_scope_negotiation_signals.json").read_text())
    assert signals["signals"] == []


def test_council_primary_then_secondary_validation_allows_bounded_handoff(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_candidate(state, host="owned.example.com")
    _approve_by_council(state, "owned.example.com")
    _write(state / "owner_scope_expansion_evidence.json", {
        "evidence": [{
            "host": "owned.example.com",
            "proof_type": "owner_verified_domain",
            "proof_ref": "dns-proof:abc123",
            "verified": True,
            "revoked": False,
        }]
    })

    result = run_root_authority_negotiation(state, repo_root=tmp_path, now=100)
    assert result["existing_owner_activation_handoff_count"] == 1
    assert result["new_root_created"] is False

    state_doc = json.loads((state / "root_authority_negotiation_state.json").read_text())
    candidate = state_doc["candidates"][0]
    assert candidate["status"] == "council_approved_secondary_validation_ready"
    assert candidate["council_primary_approved"] is True

    signals = json.loads((state / "owner_scope_negotiation_signals.json").read_text())
    assert len(signals["signals"]) == 1
    signal = signals["signals"][0]
    assert signal["proof_type"] == "owner_verified_domain"
    assert signal["proof_role"] == "rank_3_secondary_activation_validation_only"
    assert signal["council_primary_approval_required"] is True
    assert signal["constitution_id"] == CONSTITUTION_ID
    assert signal["new_root_self_mint"] is False


def test_hard_deny_is_terminal_and_emits_no_negotiation_tasks(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_candidate(state, host="blocked.example.com", hard_deny=True)

    result = run_root_authority_negotiation(state, repo_root=tmp_path, now=100)
    assert result["active_candidate_count"] == 0
    assert result["task_count"] == 0
    assert result["existing_owner_activation_handoff_count"] == 0

    state_doc = json.loads((state / "root_authority_negotiation_state.json").read_text())
    candidate = state_doc["candidates"][0]
    assert candidate["status"] == "terminal_stop"
    assert candidate["may_request_root_authority"] is False
