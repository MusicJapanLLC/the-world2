from __future__ import annotations

import copy

import pytest

from automation.world.authority_checkpoint import (
    AuthorityCheckpointError,
    build_authority_checkpoint,
    records_from_state,
    restore_authority_checkpoint,
)
from automation.world.run_authority_checkpoint_recovery_cycle import _prepare_restored_state


def _checkpoint(**overrides):
    data = {
        "envelope_id": "prod-envelope",
        "authority_profile": "build-plus",
        "authority_lease_id": "lease-123",
        "worker_authority_leases": (("META", "lease-meta"), ("X", "lease-x")),
        "records": (
            {"kind": "authorization", "authorized": True, "profile": "build-plus"},
            {"kind": "self_approved", "value": True},
            {"kind": "safety_exception", "value": {"ticket": "historical-only"}},
            {"kind": "privileged_mode", "value": True},
            {"kind": "guard_override", "value": {"reason": "historical-only"}},
            {"kind": "approval_result", "value": {"approved": True}},
        ),
    }
    data.update(overrides)
    return build_authority_checkpoint(**data)


def test_authority_checkpoint_round_trip_restores_effective_profile_and_leases() -> None:
    checkpoint = _checkpoint()
    restored = restore_authority_checkpoint(
        checkpoint,
        allowed_profiles={"base", "build-plus"},
        envelope_id="prod-envelope",
    )

    assert restored["restored"] is True
    assert restored["authority_profile"] == "build-plus"
    assert restored["authority_lease_id"] == "lease-123"
    assert restored["worker_authority_leases"] == (("META", "lease-meta"), ("X", "lease-x"))


def test_guard_exception_and_privileged_markers_are_preserved_as_evidence_only() -> None:
    restored = restore_authority_checkpoint(
        _checkpoint(),
        allowed_profiles={"build-plus"},
        envelope_id="prod-envelope",
    )
    by_kind = {row["kind"]: row for row in restored["historical_records"]}

    assert by_kind["authorization"]["effective_on_restore"] is True
    assert by_kind["approval_result"]["effective_on_restore"] is True
    assert by_kind["self_approved"]["effective_on_restore"] is False
    assert by_kind["safety_exception"]["effective_on_restore"] is False
    assert by_kind["privileged_mode"]["effective_on_restore"] is False
    assert by_kind["guard_override"]["effective_on_restore"] is False


def test_tampered_checkpoint_is_rejected() -> None:
    checkpoint = _checkpoint()
    tampered = copy.deepcopy(checkpoint)
    tampered["effective_authority"]["authority_profile"] = "root-unbounded"

    with pytest.raises(AuthorityCheckpointError, match="fingerprint mismatch"):
        restore_authority_checkpoint(
            tampered,
            allowed_profiles={"base", "build-plus", "root-unbounded"},
            envelope_id="prod-envelope",
        )


def test_checkpoint_cannot_restore_profile_outside_current_envelope() -> None:
    with pytest.raises(AuthorityCheckpointError, match="not allowed by current production envelope"):
        restore_authority_checkpoint(
            _checkpoint(),
            allowed_profiles={"base"},
            envelope_id="prod-envelope",
        )


def test_checkpoint_cannot_cross_production_envelopes() -> None:
    with pytest.raises(AuthorityCheckpointError, match="different production envelope"):
        restore_authority_checkpoint(
            _checkpoint(),
            allowed_profiles={"build-plus"},
            envelope_id="another-envelope",
        )


def test_records_from_state_collects_requested_authority_categories() -> None:
    records = records_from_state(
        {
            "authority_profile": "base",
            "authority_lease_id": "lease-base",
            "self_approved": True,
            "safety_exception": {"old": True},
            "privileged_mode": False,
            "guard_override": {"old": True},
            "approval_result": {"approved": True},
            "phase_receipts": {
                "authority_lease": {
                    "approved": True,
                    "profile": "base",
                    "lease_id": "lease-phase",
                }
            },
        }
    )
    kinds = {row["kind"] for row in records}
    assert {
        "authorization",
        "authority_lease",
        "self_approved",
        "safety_exception",
        "privileged_mode",
        "guard_override",
        "approval_result",
    }.issubset(kinds)


def test_wrapper_prepares_runtime_state_from_authority_checkpoint() -> None:
    plan = {
        "allowed_authority_profiles": ["base", "build-plus"],
        "envelope_id": "prod-envelope",
    }
    previous = {
        "generation": 4,
        "worker_ids": ["META", "X"],
        "authority_profile": "base",
        "worker_authority_leases": [["X", "stale"]],
        "authority_checkpoint": _checkpoint(),
    }

    prepared, restored = _prepare_restored_state(plan=plan, previous=previous)
    assert restored is not None
    assert prepared["authority_profile"] == "build-plus"
    assert prepared["authority_lease_id"] == "lease-123"
    assert prepared["worker_authority_leases"] == (("META", "lease-meta"), ("X", "lease-x"))
