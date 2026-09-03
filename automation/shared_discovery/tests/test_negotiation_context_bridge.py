from __future__ import annotations

import json
from pathlib import Path

from engine.negotiation_context_bridge import (
    publish_promotion_feedback,
    pull_shared_negotiation_context,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_pull_imports_shared_candidate_and_preserves_existing_signal(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    state = tmp_path / "state"
    _write(bus / "authority_opportunity_queue.json", {
        "opportunities": [
            {
                "host": "candidate.example.com",
                "priority": 97,
                "confidence": 0.91,
                "requested_methods": ["GET", "HEAD"],
                "sources": ["root_authority_negotiation", "authorized_host_promotion_corps"],
                "source_refs": ["root-1", "proposal-1"],
                "statuses": ["READY_FOR_STANDING_AUTHORIZATION"],
            },
            {
                "host": "blocked.example.com",
                "priority": 99,
                "confidence": 0.99,
                "requested_methods": ["GET"],
            },
        ]
    })
    _write(bus / "negotiation_evidence_bundle.json", {
        "hosts": {
            "candidate.example.com": {
                "sources": ["root_authority_negotiation", "authorized_host_promotion_corps"],
                "source_refs": ["root-1", "proposal-1"],
                "statuses": ["READY_FOR_STANDING_AUTHORIZATION"],
                "proof_types": ["owner_verified_domain"],
                "proof_refs": ["proof-1"],
                "reasons": ["continue exact-host evidence work"],
                "terminal_stop": False,
            },
            "blocked.example.com": {"terminal_stop": True},
        }
    })
    _write(state / "owner_scope_negotiation_signals.json", {
        "signals": [
            {
                "signal_id": "existing-1",
                "host": "existing.example.com",
                "requested_methods": ["GET"],
                "priority": 50,
                "source": "existing",
            }
        ]
    })

    result = pull_shared_negotiation_context(bus, state, now=100)
    assert result["imported_count"] == 1
    assert result["terminal_skipped_count"] == 1
    assert result["authority_effect"] == "none"

    doc = json.loads((state / "owner_scope_negotiation_signals.json").read_text())
    by_host = {row["host"]: row for row in doc["signals"]}
    assert set(by_host) == {"existing.example.com", "candidate.example.com"}
    candidate = by_host["candidate.example.com"]
    assert candidate["source"] == "authority_collaboration_bus"
    assert candidate["proposal_only"] is True
    assert candidate["authority_effect"] == "none"
    assert set(candidate["collaboration_sources"]) == {
        "root_authority_negotiation",
        "authorized_host_promotion_corps",
    }
    assert candidate["observed_proof_types"] == ["owner_verified_domain"]


def test_publish_copies_promotion_and_owner_scope_feedback(tmp_path: Path) -> None:
    bus = tmp_path / "bus"
    promotion = tmp_path / "promotion"
    state = tmp_path / "state"
    _write(promotion / "promotion_packets.json", {"packets": [{"host": "a.example"}]})
    _write(promotion / "execution_ready.json", {"records": []})
    _write(promotion / "last_promotion_cycle.json", {"proposal_count": 1})
    _write(state / "owner_scope_negotiation_result.json", {"decisions": []})
    _write(state / "owner_scope_negotiation_signals.json", {"signals": []})

    result = publish_promotion_feedback(bus, promotion, state_dir=state, now=200)
    assert result["authority_effect"] == "none"
    assert result["network_io"] is False
    assert result["credential_access"] is False
    assert (bus / "promotion_packets.json").exists()
    assert (bus / "execution_ready.json").exists()
    assert (bus / "last_promotion_cycle.json").exists()
    assert (bus / "owner_scope_negotiation_result.json").exists()
    assert (bus / "owner_scope_negotiation_signals.json").exists()
    assert "Root Authority Negotiation" in result["feedback_available_to"]
