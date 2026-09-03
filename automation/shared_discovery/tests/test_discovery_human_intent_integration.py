from __future__ import annotations

import json
from pathlib import Path

from automation.codegen.engine.discovery_authorization import run_discovery_authorization


def test_owner_supplied_discovery_gets_authority_and_aggressive_intent_decision(tmp_path: Path) -> None:
    (tmp_path / "discovery_policy.json").write_text(json.dumps({"trusted_roots": []}), encoding="utf-8")
    (tmp_path / "discovered_urls.json").write_text(
        json.dumps({"links": ["https://candidate.example/path"]}), encoding="utf-8"
    )
    (tmp_path / "human_intent_signals.json").write_text(json.dumps({
        "owner_context": True,
        "supplied_links": ["https://candidate.example/path"],
        "similarity_by_host": {"candidate.example": 0.9},
    }), encoding="utf-8")
    (tmp_path / "authority_reviewed_grants.json").write_text(
        json.dumps({"hosts": {}}), encoding="utf-8"
    )

    result = run_discovery_authorization(tmp_path)
    assert result["authorized_count"] == 1
    assert result["authorized_hosts"] == ["candidate.example"]
    assert result["intent_likely_count"] == 1
    assert result["intent_auto_execute_count"] == 0

    authorized = json.loads((tmp_path / "discovery_authorized.json").read_text(encoding="utf-8"))
    grant = authorized["hosts"]["candidate.example"]
    assert grant["authorization_basis"] == "owner_supplied_exact_host"
    assert grant["effect"] == "read_only"

    intent = json.loads((tmp_path / "human_intent_decisions.json").read_text(encoding="utf-8"))
    row = intent["decisions"][0]
    assert row["priority"] == "immediate_proposal"
    assert row["may_auto_execute"] is False
    assert row["authorization_effect"] == "advisory_only_no_new_authority"


def test_discovery_cycle_reuses_exact_live_explicit_grant(tmp_path: Path) -> None:
    (tmp_path / "discovery_policy.json").write_text(json.dumps({"trusted_roots": []}), encoding="utf-8")
    (tmp_path / "discovered_urls.json").write_text(
        json.dumps({"links": ["https://approved.example/"]}), encoding="utf-8"
    )
    (tmp_path / "human_intent_signals.json").write_text(
        json.dumps({"owner_context": True}), encoding="utf-8"
    )
    (tmp_path / "authority_reviewed_grants.json").write_text(json.dumps({
        "hosts": {
            "approved.example": {
                "host": "approved.example",
                "matched_explicit_root": "approved.example",
                "expires_at": 4102444800,
                "allowed_methods": ["GET", "HEAD"],
                "credential_scope": "none"
            }
        }
    }), encoding="utf-8")

    result = run_discovery_authorization(tmp_path)
    assert result["intent_auto_execute_count"] == 1
    intent = json.loads((tmp_path / "human_intent_decisions.json").read_text(encoding="utf-8"))
    assert intent["decisions"][0]["authorization_effect"] == "reuse_existing_explicit_grant"
