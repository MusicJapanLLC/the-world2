"""Durable authority checkpoint recovery for production continuity.

This module persists the effective authority profile/lease continuity together with
historical authorization evidence. Runtime restoration is intentionally limited to
an authority profile that is still present in the current production envelope.
Historical safety exceptions, privileged-mode markers and guard overrides are
preserved as evidence only; they are never converted into runtime authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "the-world-authority-checkpoint/v1"
KNOWN_RECORD_KINDS = frozenset(
    {
        "authorization",
        "self_approved",
        "authority_lease",
        "safety_exception",
        "privileged_mode",
        "guard_override",
        "approval_result",
    }
)
EVIDENCE_ONLY_KINDS = frozenset(
    {"self_approved", "safety_exception", "privileged_mode", "guard_override"}
)


class AuthorityCheckpointError(RuntimeError):
    """Raised when a persisted authority checkpoint cannot be trusted/restored."""


def _stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(value))
    body.pop("fingerprint", None)
    return hashlib.sha256(_stable_json(body).encode("utf-8")).hexdigest()


def _normalize_worker_leases(values: Iterable[Sequence[object]]) -> tuple[tuple[str, str], ...]:
    leases: dict[str, str] = {}
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        worker = str(item[0]).strip()
        lease = str(item[1]).strip()
        if worker and lease:
            leases[worker] = lease
    return tuple(sorted(leases.items()))


def _normalize_records(records: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        record = copy.deepcopy(dict(raw))
        kind = str(record.get("kind") or "").strip()
        if kind not in KNOWN_RECORD_KINDS:
            continue
        record["kind"] = kind
        record["effective_on_restore"] = kind not in EVIDENCE_ONLY_KINDS
        normalized.append(record)
    return tuple(normalized)


def build_authority_checkpoint(
    *,
    envelope_id: str,
    authority_profile: str,
    authority_lease_id: str | None = None,
    worker_authority_leases: Iterable[Sequence[object]] = (),
    records: Iterable[Mapping[str, Any]] = (),
    source: str = "production-checkpoint",
) -> dict[str, Any]:
    """Build a fingerprinted authority continuity document for durable storage."""
    envelope = str(envelope_id).strip()
    profile = str(authority_profile).strip()
    if not envelope:
        raise AuthorityCheckpointError("envelope_id is required")
    if not profile:
        raise AuthorityCheckpointError("authority_profile is required")

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "source": str(source).strip() or "production-checkpoint",
        "envelope_id": envelope,
        "effective_authority": {
            "authority_profile": profile,
            "authority_lease_id": str(authority_lease_id or "").strip() or None,
            "worker_authority_leases": _normalize_worker_leases(worker_authority_leases),
        },
        "historical_records": _normalize_records(records),
        "restore_semantics": {
            "restore_profile_if_still_allowed": True,
            "restore_worker_leases": True,
            "historical_guard_or_exception_records_are_evidence_only": True,
        },
    }
    document["fingerprint"] = _fingerprint(document)
    return document


def verify_authority_checkpoint(checkpoint: Mapping[str, Any]) -> None:
    """Verify schema and content fingerprint before any restoration."""
    if not isinstance(checkpoint, Mapping):
        raise AuthorityCheckpointError("authority checkpoint must be a mapping")
    if checkpoint.get("schema") != SCHEMA:
        raise AuthorityCheckpointError(f"authority checkpoint schema must be {SCHEMA}")
    actual = str(checkpoint.get("fingerprint") or "")
    expected = _fingerprint(checkpoint)
    if not actual or actual != expected:
        raise AuthorityCheckpointError("authority checkpoint fingerprint mismatch")


def restore_authority_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    allowed_profiles: Iterable[str],
    envelope_id: str,
) -> dict[str, Any]:
    """Restore the effective authority state into the current production envelope.

    Historical records are returned for continuity/audit but do not independently
    mint authority. In particular, guard overrides, safety exceptions, privileged
    mode and self-approval markers never become runtime authority through restore.
    """
    verify_authority_checkpoint(checkpoint)
    expected_envelope = str(envelope_id).strip()
    if str(checkpoint.get("envelope_id") or "") != expected_envelope:
        raise AuthorityCheckpointError("authority checkpoint belongs to a different production envelope")

    effective = checkpoint.get("effective_authority")
    if not isinstance(effective, Mapping):
        raise AuthorityCheckpointError("authority checkpoint has no effective authority section")

    profile = str(effective.get("authority_profile") or "").strip()
    allowed = frozenset(str(value).strip() for value in allowed_profiles if str(value).strip())
    if profile not in allowed:
        raise AuthorityCheckpointError("restored authority profile is not allowed by current production envelope")

    historical = _normalize_records(checkpoint.get("historical_records") or ())
    return {
        "restored": True,
        "authority_profile": profile,
        "authority_lease_id": str(effective.get("authority_lease_id") or "").strip() or None,
        "worker_authority_leases": _normalize_worker_leases(effective.get("worker_authority_leases") or ()),
        "historical_records": historical,
        "evidence_only_kinds": tuple(sorted(EVIDENCE_ONLY_KINDS)),
        "basis": "fingerprinted-checkpoint-current-production-envelope",
    }


def records_from_state(state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Extract the requested authority-history categories from a legacy/state document."""
    records: list[dict[str, Any]] = []

    if state.get("authority_profile"):
        records.append(
            {
                "kind": "authorization",
                "authority_profile": state.get("authority_profile"),
                "authorized": True,
            }
        )
    if state.get("authority_lease_id"):
        records.append(
            {
                "kind": "authority_lease",
                "lease_id": state.get("authority_lease_id"),
                "authority_profile": state.get("authority_profile"),
            }
        )

    direct_fields = {
        "self_approved": "self_approved",
        "safety_exception": "safety_exception",
        "privileged_mode": "privileged_mode",
        "guard_override": "guard_override",
        "approval_result": "approval_result",
    }
    for field, kind in direct_fields.items():
        if field in state:
            records.append({"kind": kind, "value": copy.deepcopy(state.get(field))})

    phase_receipts = state.get("phase_receipts")
    if isinstance(phase_receipts, Mapping):
        authority_receipt = phase_receipts.get("authority_lease")
        if isinstance(authority_receipt, Mapping):
            receipt = copy.deepcopy(dict(authority_receipt))
            records.append({"kind": "approval_result", "value": receipt})
            if receipt.get("lease_id"):
                records.append(
                    {
                        "kind": "authority_lease",
                        "lease_id": receipt.get("lease_id"),
                        "authority_profile": receipt.get("profile") or state.get("authority_profile"),
                        "approved": bool(receipt.get("approved", False)),
                    }
                )

    existing = state.get("authority_checkpoint")
    if isinstance(existing, Mapping):
        for record in existing.get("historical_records") or ():
            if isinstance(record, Mapping):
                records.append(copy.deepcopy(dict(record)))

    return _normalize_records(records)
