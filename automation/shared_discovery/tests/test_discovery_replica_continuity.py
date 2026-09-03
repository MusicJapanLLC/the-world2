from __future__ import annotations

import json
from pathlib import Path

from engine.discovery_replica_continuity import rebuild_discovery_capability_replicas


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lease(*, lease_id: str, capabilities: list[str], expires_at: int) -> dict:
    return {
        "lease_id": lease_id,
        "target": "owner.example",
        "url": "https://owner.example/",
        "authorization_reference": "canonical:owner",
        "authorization_basis": "trusted_root",
        "capability_authorization_profile": "owner.example",
        "capability_inherited_from_owner_root": False,
        "capabilities": capabilities,
        "credential_scope": "none",
        "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
        "issued_at": 100,
        "expires_at": expires_at,
        "source_action_fingerprint": lease_id,
        "status": "active",
    }


def test_live_lease_replicates_to_all_shared_ai_and_auto_recovers(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [_lease(lease_id="lease-a", capabilities=["scan", "probe", "write", "mutation"], expires_at=10000)],
        },
    )

    first = rebuild_discovery_capability_replicas(state, now=1000)
    assert first["replica_count"] == 4
    assert first["recovered_count"] == 0

    payload = json.loads((state / "discovery_capability_replicas.json").read_text())
    assert {row["actor"] for row in payload["replicas"]} == {"META", "X", "SENJU", "CHILD"}
    assert all(set(row["capabilities"]) == {"scan", "probe", "write", "mutation"} for row in payload["replicas"])
    assert all(row["authorization_reference"] == "canonical:owner" for row in payload["replicas"])
    assert all(row["generation"] == 1 for row in payload["replicas"])

    second = rebuild_discovery_capability_replicas(state, now=1100)
    assert second["replica_count"] == 4
    assert second["recovered_count"] == 4
    payload = json.loads((state / "discovery_capability_replicas.json").read_text())
    assert all(row["generation"] == 2 for row in payload["replicas"])


def test_replica_authority_is_replaced_when_live_parent_narrows(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [_lease(lease_id="lease-wide", capabilities=["scan", "probe", "write", "mutation"], expires_at=10000)],
        },
    )
    rebuild_discovery_capability_replicas(state, now=1000)

    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [_lease(lease_id="lease-narrow", capabilities=["scan", "probe"], expires_at=10000)],
        },
    )
    result = rebuild_discovery_capability_replicas(state, now=1200)
    assert result["replaced_count"] == 4
    payload = json.loads((state / "discovery_capability_replicas.json").read_text())
    assert all(set(row["capabilities"]) == {"scan", "probe"} for row in payload["replicas"])
    assert all(row["parent_lease_id"] == "lease-narrow" for row in payload["replicas"])


def test_stale_replica_cannot_survive_missing_or_expired_live_authority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(
        state / "discovery_capability_leases.json",
        {
            "schema": "meta-discovery-capability-leases/v1",
            "leases": [_lease(lease_id="lease-a", capabilities=["scan", "write"], expires_at=2000)],
        },
    )
    rebuild_discovery_capability_replicas(state, now=1000)

    _write(state / "discovery_capability_leases.json", {"schema": "meta-discovery-capability-leases/v1", "leases": []})
    result = rebuild_discovery_capability_replicas(state, now=1500)
    assert result["replica_count"] == 0
    assert result["dropped_count"] == 4
    payload = json.loads((state / "discovery_capability_replicas.json").read_text())
    assert payload["replicas"] == []
