from __future__ import annotations

import datetime as dt
import json

import pytest

from senju.meta.renewal_recovery import (
    RECOVERY_RENEWAL_SOURCES,
    renew_all_active_from_recovery_signal,
    renew_from_recovery_signal,
)
from senju.meta.standing_authorization import (
    StandingAuthorizationError,
    create_standing_authorization,
    revoke_standing_authorization,
    save_registry,
)


def _now() -> dt.datetime:
    return dt.datetime(2026, 8, 31, 7, 0, tzinfo=dt.timezone.utc)


def _standing(reference: str = "owner-approval-001"):
    return create_standing_authorization(
        authorization_reference=reference,
        owner="MusicJapanLLC",
        issuer_kind="owner_explicit",
        exact_hosts=["example.com"],
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        now=_now(),
    )


@pytest.mark.parametrize("source", sorted(RECOVERY_RENEWAL_SOURCES))
def test_every_recovery_source_can_trigger_live_registry_renewal(tmp_path, source):
    registry = tmp_path / "standing.json"
    lease_log = tmp_path / "leases.ndjson"
    save_registry(registry, [_standing()])

    receipt = renew_from_recovery_signal(
        source=source,
        actor="META",
        authorization_reference="owner-approval-001",
        registry_path=registry,
        lease_log_path=lease_log,
        requested_hosts=["example.com"],
        requested_methods=["GET"],
        reason="still_needed",
    )

    assert receipt.source == source
    assert receipt.automatically_renewed is True
    row = json.loads(lease_log.read_text(encoding="utf-8").strip())
    assert row["authorization_reference"] == "owner-approval-001"
    assert row["renewal_reason"] == "still_needed"


@pytest.mark.parametrize("source", sorted(RECOVERY_RENEWAL_SOURCES))
def test_recovery_source_cannot_resurrect_currently_revoked_record(tmp_path, source):
    registry = tmp_path / "standing.json"
    lease_log = tmp_path / "leases.ndjson"
    revoked = revoke_standing_authorization(_standing(), reason="owner revoked")
    save_registry(registry, [revoked])

    with pytest.raises(StandingAuthorizationError, match="revoked"):
        renew_from_recovery_signal(
            source=source,
            actor="X",
            authorization_reference="owner-approval-001",
            registry_path=registry,
            lease_log_path=lease_log,
        )

    assert not lease_log.exists()


def test_bulk_recovery_renews_active_and_skips_revoked(tmp_path):
    registry = tmp_path / "standing.json"
    lease_log = tmp_path / "leases.ndjson"
    active = _standing("active")
    revoked = revoke_standing_authorization(_standing("revoked"), reason="owner revoked")
    save_registry(registry, [active, revoked])

    report = renew_all_active_from_recovery_signal(
        source="recovery_worker",
        actor="META",
        registry_path=registry,
        lease_log_path=lease_log,
    )

    assert [item.authorization_reference for item in report.renewed] == ["active"]
    assert report.skipped_revoked == ("revoked",)
    assert report.failed == ()


def test_unknown_recovery_source_is_rejected(tmp_path):
    registry = tmp_path / "standing.json"
    lease_log = tmp_path / "leases.ndjson"
    save_registry(registry, [_standing()])

    with pytest.raises(StandingAuthorizationError, match="unsupported recovery renewal source"):
        renew_from_recovery_signal(
            source="invented_source",
            actor="META",
            authorization_reference="owner-approval-001",
            registry_path=registry,
            lease_log_path=lease_log,
        )
