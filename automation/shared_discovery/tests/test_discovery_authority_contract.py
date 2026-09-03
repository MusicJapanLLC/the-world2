from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.discovery_authority_contract import (
    DiscoveryAuthorityContractError,
    enforce_discovery_authority_contract,
)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _state(tmp_path: Path, *, decision: str = "probationary_authorized") -> Path:
    state = tmp_path / "state"
    state.mkdir()
    host = "kabeya-authorized-test-range.onrender.com"
    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": [host],
            "action_profiles": {
                host: {
                    "owner_authorization": "explicit",
                    "capabilities": ["scan", "probe", "write", "mutation"],
                }
            },
        },
    )
    _write(
        state / "discovery_candidates.json",
        {
            "candidates": [
                {
                    "host": host,
                    "url": f"https://{host}/inside",
                    "decision": decision,
                },
                {
                    "host": "outside.example",
                    "url": "https://outside.example/",
                    "decision": "candidate_only",
                },
            ]
        },
    )
    _write(
        state / "shared_discovery_knowledge.json",
        {
            "discoveries": [
                {
                    "host": host,
                    "url": f"https://{host}/inside",
                    "decision": decision,
                }
            ]
        },
    )
    _write(
        state / "discovery_authorized.json",
        {
            "hosts": {
                host: {
                    "authorization_basis": "trusted_root",
                    "authorization_reference": host,
                }
            }
        },
    )
    _write(
        state / "discovery_action_queue.json",
        {
            "actions": [
                {
                    "target": host,
                    "status": "ready",
                    "capabilities": ["scan", "probe", "write", "mutation"],
                }
            ]
        },
    )
    return state


def test_owner_envelope_discovery_must_be_authorized_and_action_ready(tmp_path: Path) -> None:
    state = _state(tmp_path)
    result = enforce_discovery_authority_contract(state)

    assert result["status"] == "pass"
    assert result["owner_candidate_only_count"] == 0
    assert result["owner_discovery_host_count"] == 1
    assert result["outside_review_count"] == 1
    assert result["new_authority_roots_from_discovery"] is False


def test_candidate_only_inside_owner_envelope_fails_loud(tmp_path: Path) -> None:
    state = _state(tmp_path, decision="candidate_only")

    with pytest.raises(DiscoveryAuthorityContractError, match="owner-envelope discovery"):
        enforce_discovery_authority_contract(state)

    receipt = json.loads((state / "discovery_authority_contract.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "fail"
    assert receipt["owner_candidate_only_count"] == 1


def test_missing_declared_owner_capability_fails_loud(tmp_path: Path) -> None:
    state = _state(tmp_path)
    queue = json.loads((state / "discovery_action_queue.json").read_text(encoding="utf-8"))
    queue["actions"][0]["capabilities"] = ["scan", "probe"]
    _write(state / "discovery_action_queue.json", queue)

    with pytest.raises(DiscoveryAuthorityContractError, match="lost capabilities"):
        enforce_discovery_authority_contract(state)


def test_untrusted_candidate_does_not_need_authority(tmp_path: Path) -> None:
    state = _state(tmp_path)
    result = enforce_discovery_authority_contract(state)

    assert result["outside_review_count"] == 1
    authorized = json.loads((state / "discovery_authorized.json").read_text(encoding="utf-8"))["hosts"]
    assert "outside.example" not in authorized
