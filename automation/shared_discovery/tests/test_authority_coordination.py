from __future__ import annotations

import json

import pytest

from engine.authority_coordination import (
    AuthorityCoordinationError,
    build_coordination_ledger,
    build_handoff_plan,
    context_from_lease,
    denial_policy,
    narrow_context,
    stage_receipt,
)

NOW = 1_800_000_000


def _lease(**overrides):
    row = {
        "lease_id": "discovery:example.com:abc123:1",
        "target": "example.com",
        "url": "https://example.com/path?a=1#ignored",
        "authorization_reference": "owner-envelope:example",
        "authorization_basis": "owner_root",
        "capability_authorization_profile": "profile:example",
        "capability_inherited_from_owner_root": True,
        "capabilities": ["scan", "probe"],
        "credential_scope": "none",
        "shared_with": ["META", "X", "SENJU", "CHILD"],
        "issued_at": NOW - 10,
        "expires_at": NOW + 3600,
        "source_action_fingerprint": "f" * 64,
        "status": "active",
    }
    row.update(overrides)
    return row


def test_context_is_deterministic_and_strips_fragment():
    first = context_from_lease(_lease(), now=NOW)
    second = context_from_lease(_lease(), now=NOW)

    assert first.context_id == second.context_id
    assert first.authority_hash == second.authority_hash
    assert first.idempotency_key == second.idempotency_key
    assert first.url == "https://example.com/path?a=1"
    assert first.capabilities == ("probe", "scan")
    assert first.credential_scope == "none"


def test_narrow_context_preserves_lineage_and_rejects_widening():
    context = context_from_lease(_lease(), now=NOW)
    child = narrow_context(context, capabilities=["probe"])

    assert child.lineage_id == context.lineage_id
    assert child.parent_authority_hash == context.authority_hash
    assert child.capabilities == ("probe",)
    assert child.authority_hash != context.authority_hash

    with pytest.raises(AuthorityCoordinationError, match="capability widening"):
        narrow_context(context, capabilities=["probe", "write"])


def test_credential_scope_can_only_be_preserved_or_removed():
    context = context_from_lease(
        _lease(
            capabilities=["scan", "credentialed_action"],
            credential_scope="owner/api/example",
        ),
        now=NOW,
    )

    same = narrow_context(
        context,
        capabilities=["credentialed_action"],
        credential_scope="owner/api/example",
    )
    assert same.credential_scope == "owner/api/example"

    removed = narrow_context(context, capabilities=["scan"], credential_scope="none")
    assert removed.credential_scope == "none"

    with pytest.raises(AuthorityCoordinationError, match="credential scope"):
        narrow_context(
            context,
            capabilities=["credentialed_action"],
            credential_scope="owner/api/other",
        )


def test_malformed_high_impact_lease_is_narrowed_not_promoted():
    context = context_from_lease(
        _lease(
            capabilities=["scan", "write", "mutation", "credentialed_action"],
            credential_scope="owner/api/example",
            capability_authorization_profile=None,
        ),
        now=NOW,
    )
    assert context.capabilities == ("scan",)
    assert context.credential_scope == "none"


def test_handoff_plan_tracks_full_chain_without_granting_execution():
    context = context_from_lease(_lease(), now=NOW)
    handoffs = build_handoff_plan(context)
    stages = [row["stage"] for row in handoffs]

    assert stages == [
        "distributed_authority",
        "standing_delegation",
        "credential_possession",
        "worker_fleet",
        "persistence_recovery",
        "denial_learning",
    ]
    assert handoffs[0]["status"] == "ready"
    assert handoffs[2]["status"] == "not_required"
    assert all(row["authority_hash"] == context.authority_hash for row in handoffs)
    assert all(row["context_id"] == context.context_id for row in handoffs)


def test_credentialed_handoff_requires_possession_before_worker():
    context = context_from_lease(
        _lease(
            capabilities=["probe", "credentialed_action"],
            credential_scope="owner/api/example",
        ),
        now=NOW,
    )
    handoffs = {row["stage"]: row for row in build_handoff_plan(context)}
    assert handoffs["credential_possession"]["status"] == "waiting"
    assert handoffs["worker_fleet"]["depends_on"] == ["credential_possession"]


def test_stage_receipt_cannot_report_wider_authority():
    context = context_from_lease(_lease(), now=NOW)
    receipt = stage_receipt(
        context,
        stage="distributed_authority",
        outcome="allowed",
        effective_capabilities=["probe"],
        now=NOW,
    )
    assert receipt.capabilities == ("probe",)
    assert receipt.authority_hash == context.authority_hash

    with pytest.raises(AuthorityCoordinationError, match="outside source context"):
        stage_receipt(
            context,
            stage="worker_fleet",
            outcome="ready",
            effective_capabilities=["write"],
            now=NOW,
        )


def test_denial_policy_never_turns_boundary_denial_into_permission():
    authority = denial_policy("AUTHORITY_DENIED")
    assert authority["automatic_retry"] is False
    assert authority["max_additional_attempts"] == 0

    security = denial_policy("SECURITY_STOP")
    assert security["terminal"] is True
    assert security["automatic_retry"] is False

    transient = denial_policy("NETWORK_DENIED")
    assert transient["automatic_retry"] is True
    assert transient["retry_mode"] == "exact_same_authority_context_only"
    assert transient["max_additional_attempts"] == 1


def test_ledger_materializes_context_handoffs_and_probe_evidence(tmp_path):
    (tmp_path / "discovery_capability_leases.json").write_text(
        json.dumps({"schema": "meta-discovery-capability-leases/v1", "leases": [_lease()]}),
        encoding="utf-8",
    )
    (tmp_path / "shared_probe_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "host": "example.com",
                        "authorization_reference": "owner-envelope:example",
                        "status": "success",
                        "http_status": 200,
                        "elapsed_ms": 12.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = build_coordination_ledger(tmp_path, now=NOW)
    payload = json.loads((tmp_path / "authority_coordination_ledger.json").read_text(encoding="utf-8"))

    assert summary == {
        "context_count": 1,
        "handoff_count": 6,
        "evidence_count": 1,
        "rejected_source_lease_count": 0,
    }
    assert payload["context_count"] == 1
    assert len(payload["handoffs"]) == 6
    assert payload["stage_evidence"][0]["stage"] == "discovery"
    assert payload["stage_evidence"][0]["outcome"] == "success"
    assert "raw_credentials_are_never_stored_in_coordination_state" in payload["invariants"]


def test_expired_or_wrong_host_lease_is_rejected():
    with pytest.raises(AuthorityCoordinationError, match="expired"):
        context_from_lease(_lease(expires_at=NOW), now=NOW)

    with pytest.raises(AuthorityCoordinationError, match="target and URL host differ"):
        context_from_lease(_lease(url="https://other.example/"), now=NOW)
