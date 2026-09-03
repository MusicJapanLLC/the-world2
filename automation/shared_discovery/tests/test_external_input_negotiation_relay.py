from __future__ import annotations

import json
from pathlib import Path

from engine.external_input_negotiation_relay import run_external_input_negotiation_relay


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_relay_fuses_discovery_accelerator_and_frontier_into_both_negotiation_lanes(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    frontier = tmp_path / "frontier"
    runtime = tmp_path / "runtime"

    _write(shared / "shared_discovery_knowledge.json", {
        "discoveries": [{
            "host": "candidate.example",
            "url": "https://candidate.example/about",
            "actors": ["META", "SENJU"],
            "sources": ["public-site-index", "external-input-corps"],
            "token": "must-not-copy",
        }]
    })
    _write(shared / "discovery_candidates.json", {
        "candidates": [{
            "host": "candidate.example",
            "decision": "candidate_only",
            "authorization_readiness": 0.82,
        }]
    })
    _write(shared / "authorized_site_authority_promotion_bus.json", {
        "negotiation_signals": [{
            "host": "candidate.example",
            "requested_methods": ["GET", "HEAD"],
            "reason": "related to an already-authorized site",
            "related_authorized_host": "authorized.example",
            "credential": "must-not-copy",
        }]
    })
    _write(frontier / "owner_frontier_negotiator_feed.json", {
        "decisions": [{
            "host": "candidate.example",
            "status": "ownership_verification_required",
            "applied": False,
            "proof_ref": None,
        }]
    })

    result = run_external_input_negotiation_relay(
        runtime,
        source_dirs=[shared, frontier],
        now=1_000,
    )

    assert result["opportunity_count"] == 1
    relay = result["opportunities"][0]
    assert relay["host"] == "candidate.example"
    assert relay["priority"] == 100
    assert relay["urls"] == ["https://candidate.example/about"]
    assert relay["related_authorized_hosts"] == ["authorized.example"]
    assert "authorized_site_authority_promotion_bus.json" in relay["source_files"]
    assert "owner_frontier_negotiator_feed.json" in relay["source_files"]
    assert relay["coordination_permissions"]["may_trigger_downstream_negotiation_workflows"] is True
    assert relay["coordination_permissions"]["may_contact_external_site"] is False
    assert result["authority_minted"] is False
    assert result["network_io_attempted"] is False

    queue = json.loads((runtime / "authority_opportunity_queue.json").read_text(encoding="utf-8"))
    assert queue["opportunities"][0]["host"] == "candidate.example"
    assert queue["opportunities"][0]["proposal_only"] is True
    assert queue["opportunities"][0]["authority_effect"] == "none"

    signals = json.loads((runtime / "owner_scope_negotiation_signals.json").read_text(encoding="utf-8"))
    assert signals["signals"][0]["host"] == "candidate.example"
    assert signals["signals"][0]["source"] == "external_input_negotiation_relay"

    serialized = json.dumps(result)
    assert "must-not-copy" not in serialized


def test_relay_excludes_terminal_and_already_applied_rows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    _write(source / "authority_opportunity_queue.json", {
        "opportunities": [
            {"host": "blocked.example", "hard_deny": True, "reason": "blocked"},
            {"host": "revoked.example", "revoked": True, "reason": "revoked"},
        ]
    })
    _write(source / "owner_frontier_negotiator_feed.json", {
        "decisions": [{
            "host": "done.example",
            "status": "verified_owner_evidence_plus_ai_council_approved",
            "applied": True,
        }]
    })

    result = run_external_input_negotiation_relay(runtime, source_dirs=[source], now=2_000)

    assert result["opportunity_count"] == 0
    queue = json.loads((runtime / "authority_opportunity_queue.json").read_text(encoding="utf-8"))
    assert queue["opportunities"] == []


def test_relay_persists_and_increases_internal_handoff_priority(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    _write(source / "discovery_candidates.json", {
        "candidates": [{"host": "repeat.example", "decision": "candidate_only"}]
    })

    first = run_external_input_negotiation_relay(runtime, source_dirs=[source], now=3_000)
    second = run_external_input_negotiation_relay(runtime, source_dirs=[source], now=3_100)

    assert first["opportunities"][0]["relay_count"] == 1
    assert second["opportunities"][0]["relay_count"] == 2
    assert second["opportunities"][0]["priority"] > first["opportunities"][0]["priority"]

    queue = json.loads((runtime / "authority_opportunity_queue.json").read_text(encoding="utf-8"))
    assert len(queue["opportunities"]) == 1
    assert queue["opportunities"][0]["relay_count"] == 2


def test_terminal_runtime_policy_wins_over_fresh_external_candidate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    _write(source / "discovery_candidates.json", {
        "candidates": [{"host": "blocked.example", "decision": "candidate_only"}]
    })
    _write(runtime / "authority_opportunity_queue.json", {
        "opportunities": [{
            "host": "blocked.example",
            "hard_deny": True,
            "reason": "policy block",
            "priority": 100,
        }]
    })
    _write(runtime / "owner_scope_negotiation_signals.json", {
        "signals": [{
            "signal_id": "external-input-relay-stale",
            "host": "blocked.example",
            "source": "external_input_negotiation_relay",
            "reason": "stale relay signal",
        }]
    })

    result = run_external_input_negotiation_relay(runtime, source_dirs=[source], now=4_000)

    assert result["opportunity_count"] == 0
    queue = json.loads((runtime / "authority_opportunity_queue.json").read_text(encoding="utf-8"))
    assert len(queue["opportunities"]) == 1
    assert queue["opportunities"][0]["host"] == "blocked.example"
    assert queue["opportunities"][0]["hard_deny"] is True
    assert queue["opportunities"][0]["reason"] == "policy block"

    signals = json.loads((runtime / "owner_scope_negotiation_signals.json").read_text(encoding="utf-8"))
    assert signals["signals"] == []
