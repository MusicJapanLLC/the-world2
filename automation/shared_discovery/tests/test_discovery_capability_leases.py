from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.discovery_capability_leases import (
    DiscoveryCapabilityLeaseError,
    authorize_discovery_capability,
    issue_discovery_capability_leases,
    load_discovery_capability_leases,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _queue_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "target": "api.owner.example",
        "url": "https://api.owner.example/v1/resource",
        "authorization_reference": "trusted-root:owner.example",
        "authorization_basis": "trusted_root",
        "expires_at": 2_000_000,
        "capabilities": ["scan", "probe", "write", "mutation", "credentialed_action"],
        "credential_scope": "owner-api-service",
        "capability_authorization_profile": "owner.example",
        "capability_inherited_from_owner_root": True,
        "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
        "status": "ready",
    }
    row.update(overrides)
    return row


def test_inherited_owner_root_capabilities_become_shared_operational_authority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "discovery_action_queue.json", {"actions": [_queue_row()]})

    result = issue_discovery_capability_leases(state, now=1_000_000, lease_seconds=3600)

    assert result["lease_count"] == 1
    assert result["high_impact_lease_count"] == 1
    assert result["inherited_high_impact_lease_count"] == 1
    assert result["credentialed_lease_count"] == 1

    lease = load_discovery_capability_leases(state)[0]
    assert lease.target == "api.owner.example"
    assert lease.capability_authorization_profile == "owner.example"
    assert lease.capability_inherited_from_owner_root is True
    assert set(lease.capabilities) == {
        "scan",
        "probe",
        "write",
        "mutation",
        "credentialed_action",
    }
    assert lease.credential_scope == "owner-api-service"
    assert {"META", "X", "SENJU", "CHILD", "AI"}.issubset(set(lease.shared_with))
    assert lease.expires_at == 1_003_600

    granted = authorize_discovery_capability(
        state,
        target="api.owner.example",
        capability="mutation",
        now=1_000_001,
    )
    assert granted.lease_id == lease.lease_id


def test_credentialed_action_is_not_issued_without_existing_named_scope(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(
        state / "discovery_action_queue.json",
        {"actions": [_queue_row(credential_scope="none")]},
    )

    issue_discovery_capability_leases(state, now=1_000_000)
    lease = load_discovery_capability_leases(state)[0]

    assert "credentialed_action" not in lease.capabilities
    assert lease.credential_scope == "none"
    assert {"write", "mutation"}.issubset(set(lease.capabilities))


def test_high_impact_capability_without_explicit_profile_is_reduced_to_scan_probe(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(
        state / "discovery_action_queue.json",
        {
            "actions": [
                _queue_row(
                    capability_authorization_profile=None,
                    capability_inherited_from_owner_root=False,
                )
            ]
        },
    )

    issue_discovery_capability_leases(state, now=1_000_000)
    lease = load_discovery_capability_leases(state)[0]

    assert set(lease.capabilities) == {"scan", "probe"}
    assert lease.credential_scope == "none"


def test_live_queue_rebuild_removes_stale_capability_instead_of_preserving_it(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "discovery_action_queue.json", {"actions": [_queue_row()]})
    issue_discovery_capability_leases(state, now=1_000_000)
    first = load_discovery_capability_leases(state)[0]
    assert "mutation" in first.capabilities

    _write(
        state / "discovery_action_queue.json",
        {
            "actions": [
                _queue_row(
                    capabilities=["scan", "probe"],
                    credential_scope="none",
                    capability_authorization_profile="api.owner.example",
                    capability_inherited_from_owner_root=False,
                )
            ]
        },
    )
    issue_discovery_capability_leases(state, now=1_000_100)
    second = load_discovery_capability_leases(state)[0]

    assert set(second.capabilities) == {"scan", "probe"}
    assert "mutation" not in second.capabilities
    assert second.lease_id != first.lease_id


def test_expired_or_removed_action_drops_existing_lease(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "discovery_action_queue.json", {"actions": [_queue_row()]})
    issue_discovery_capability_leases(state, now=1_000_000)
    assert len(load_discovery_capability_leases(state)) == 1

    _write(
        state / "discovery_action_queue.json",
        {"actions": [_queue_row(expires_at=1_000_050)]},
    )
    result = issue_discovery_capability_leases(state, now=1_000_100)

    assert result["lease_count"] == 0
    assert load_discovery_capability_leases(state) == ()
    events = (state / "capability_lease_events.ndjson").read_text(encoding="utf-8")
    assert '"event": "dropped"' in events


def test_lease_is_exact_target_and_time_bounded(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _write(state / "discovery_action_queue.json", {"actions": [_queue_row()]})
    issue_discovery_capability_leases(state, now=1_000_000, lease_seconds=300)

    with pytest.raises(DiscoveryCapabilityLeaseError, match="no active"):
        authorize_discovery_capability(
            state,
            target="other.owner.example",
            capability="probe",
            now=1_000_001,
        )

    with pytest.raises(DiscoveryCapabilityLeaseError, match="not active"):
        authorize_discovery_capability(
            state,
            target="api.owner.example",
            capability="mutation",
            now=1_000_301,
        )
