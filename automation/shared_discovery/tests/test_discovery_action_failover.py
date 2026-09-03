from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from engine import discovery_action_failover as module


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeLease:
    target = "owner.example"
    capabilities = ("write",)
    authorization_reference = "canonical:owner"
    credential_scope = "none"

    def is_active(self) -> bool:
        return True


def _policy() -> dict:
    return {
        "action_profiles": {
            "owner.example": {
                "owner_authorization": "explicit",
                "capabilities": ["write"],
                "credential_scope": "none",
                "external_actions": {
                    "write": [
                        {
                            "id": "write-1",
                            "method": "POST",
                            "path": "/synthetic/write",
                            "content_type": "application/json",
                            "body": "{\"synthetic\":true}",
                        }
                    ]
                },
            }
        }
    }


def _authorized_target() -> dict:
    return {
        "targets": [
            {
                "host": "owner.example",
                "owner_authorization": "explicit",
                "allowed_interactions": ["GET", "HEAD", "POST"],
            }
        ]
    }


def test_transient_failure_learns_and_switches_strategy_under_same_authority(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(state / "discovery_policy.json", _policy())
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", _authorized_target())
    _write(
        state / "discovery_external_action_receipts.json",
        {
            "receipts": [
                {
                    "target": "owner.example",
                    "capability": "write",
                    "action_id": "write-1",
                    "method": "POST",
                    "status": "failed",
                    "classification": "transient_transport_failure",
                }
            ]
        },
    )
    monkeypatch.setattr(module, "load_discovery_capability_leases", lambda state_dir: (FakeLease(),))

    calls: list[tuple[int, str, str, bytes | None]] = []

    class FakeClient:
        def __init__(self, policy):
            self.policy = policy

        def contact_with_body(self, url, *, method, body=None, headers=None):
            calls.append((self.policy.retries, method, url, body))
            if self.policy.retries == 2:
                raise TimeoutError("temporary timeout")
            return SimpleNamespace(
                body=b"ok",
                receipt=SimpleNamespace(
                    status=200,
                    final_url=url,
                    response_sha256="ab" * 32,
                ),
            )

    monkeypatch.setattr(module, "ExternalContactClient", FakeClient)
    result = module.run_discovery_action_failover(state, repo_root=repo, max_actions=4)

    assert result["attempted"] == 2
    assert result["succeeded"] == 1
    assert result["failed_attempts"] == 1
    assert [row[0] for row in calls] == [2, 3]
    assert all(row[1] == "POST" for row in calls)
    assert all(row[2] == "https://owner.example/synthetic/write" for row in calls)
    assert all(row[3] == b'{"synthetic":true}' for row in calls)

    learning = json.loads((state / "external_action_route_learning.json").read_text())
    row = learning["actions"]["owner.example|write|write-1"]
    assert row["preferred_strategy"] == "patient"
    assert row["successes"] == 1
    assert row["failures"] == 1


def test_boundary_denial_is_learned_but_never_sent_to_transport(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    _write(
        state / "discovery_external_action_receipts.json",
        {
            "receipts": [
                {
                    "target": "owner.example",
                    "capability": "write",
                    "action_id": "write-1",
                    "method": "POST",
                    "status": "failed",
                    "classification": "boundary_denial",
                }
            ]
        },
    )

    class ForbiddenClient:
        def __init__(self, policy):
            raise AssertionError("boundary denial must never reach transport")

    monkeypatch.setattr(module, "ExternalContactClient", ForbiddenClient)
    monkeypatch.setattr(module, "load_discovery_capability_leases", lambda state_dir: ())
    result = module.run_discovery_action_failover(state, repo_root=repo)

    assert result["attempted"] == 0
    assert result["succeeded"] == 0
    assert result["boundary_denials_learned"] == 1
    assert result["receipts"][0]["decision"] == "learn_and_preserve_boundary"

    learning = json.loads((state / "external_action_route_learning.json").read_text())
    assert learning["actions"]["owner.example|write|write-1"]["boundary_denials"] == 1
