from __future__ import annotations

import json
import time
from pathlib import Path

from plan_discovery_external_actions import build_plan


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_planner_enumerates_authorized_actions_without_network_io(tmp_path: Path) -> None:
    now = int(time.time())
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [{
                "lease_id": "lease-1",
                "target": "owner.example",
                "url": "https://owner.example/",
                "authorization_reference": "canonical:owner",
                "authorization_basis": "trusted_root",
                "capability_authorization_profile": "owner.example",
                "capability_inherited_from_owner_root": False,
                "capabilities": ["write", "mutation"],
                "credential_scope": "none",
                "shared_with": ["META", "X", "SENJU"],
                "issued_at": now - 10,
                "expires_at": now + 3600,
                "source_action_fingerprint": "abc123",
                "status": "active",
            }],
        },
    )
    _write(
        state / "discovery_policy.json",
        {
            "action_profiles": {
                "owner.example": {
                    "owner_authorization": "explicit",
                    "external_actions": {
                        "write": [{"id": "post-1", "method": "POST", "path": "/synthetic", "body": "{}"}],
                        "mutation": [{"id": "patch-1", "method": "PATCH", "path": "/synthetic", "body": "{}"}],
                    },
                }
            }
        },
    )
    _write(
        repo / "AUTHORIZED_TEST_TARGETS.json",
        {"targets": [{
            "host": "owner.example",
            "owner_authorization": "explicit",
            "allowed_interactions": ["POST", "PATCH"],
        }]},
    )

    result = build_plan(state, repo_root=repo, max_candidates=999)

    assert result["max_candidates"] == 300
    assert result["candidate_count"] == 2
    assert result["network_io_attempted"] is False
    assert result["authority_minted"] is False
    assert [row["method"] for row in result["candidates"]] == ["POST", "PATCH"]
