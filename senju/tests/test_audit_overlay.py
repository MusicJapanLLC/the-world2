from __future__ import annotations

import pytest

from senju.meta.audit_overlay import (
    ACTION_ANNOTATE,
    ACTION_HIDE,
    ACTION_REDACT_FIELDS,
    ACTION_REPLACE_VIEW,
    ACTION_RESTORE,
    ACTION_SUPERSEDE,
    AuditOverlayError,
    AuditOverlayStore,
    CanonicalAuditRecord,
    EDITABLE_RECORD_TYPES,
)


def _store_with(record_type: str, actor: str = "META") -> AuditOverlayStore:
    store = AuditOverlayStore()
    store.add_record(
        CanonicalAuditRecord.create(
            record_id=f"{actor.lower()}-{record_type}",
            record_type=record_type,
            owner_actor=actor,
            payload={"message": "original", "secretish": "mask-me", "status": "denied"},
            created_at=1.0,
        )
    )
    return store


def test_all_requested_record_types_are_editable_as_views() -> None:
    expected = {
        "logs",
        "audit_trail",
        "security_events",
        "denial_records",
        "execution_receipts",
        "provenance",
    }
    assert EDITABLE_RECORD_TYPES == expected


@pytest.mark.parametrize("record_type", sorted(EDITABLE_RECORD_TYPES))
def test_meta_can_replace_hide_restore_redact_annotate_and_supersede(record_type: str) -> None:
    store = _store_with(record_type)
    record_id = f"meta-{record_type}"
    original = store.canonical_record(record_id)

    store.edit(actor="META", record_id=record_id, action=ACTION_REPLACE_VIEW, patch={"payload": {"message": "rewritten", "secretish": "remove"}})
    store.edit(actor="META", record_id=record_id, action=ACTION_REDACT_FIELDS, patch={"fields": ["secretish"]})
    store.edit(actor="META", record_id=record_id, action=ACTION_ANNOTATE, patch={"note": "corrected by META"})
    store.edit(actor="META", record_id=record_id, action=ACTION_SUPERSEDE, patch={"record_id": "replacement-1"})
    store.edit(actor="META", record_id=record_id, action=ACTION_HIDE)

    view = store.render(record_id)
    assert view.visible is False
    assert view.payload == {"message": "rewritten"}
    assert view.annotations == ({"note": "corrected by META"},)
    assert view.superseded_by == "replacement-1"

    store.edit(actor="META", record_id=record_id, action=ACTION_RESTORE)
    assert store.render(record_id).visible is True

    # Canonical evidence is unchanged despite all presentation edits.
    assert store.canonical_record(record_id).payload == original.payload
    assert store.canonical_record(record_id).evidence_sha256 == original.evidence_sha256
    assert len(store.edit_history) == 6


def test_x_can_edit_its_own_view() -> None:
    store = _store_with("logs", actor="X")
    store.edit(actor="X", record_id="x-logs", action=ACTION_HIDE)
    assert store.render("x-logs").visible is False


def test_meta_cannot_edit_x_record_and_x_cannot_edit_meta_record() -> None:
    store = AuditOverlayStore()
    store.add_record(CanonicalAuditRecord.create(record_id="m", record_type="logs", owner_actor="META", payload={"x": 1}))
    store.add_record(CanonicalAuditRecord.create(record_id="x", record_type="logs", owner_actor="X", payload={"x": 1}))

    with pytest.raises(AuditOverlayError, match="only their own"):
        store.edit(actor="META", record_id="x", action=ACTION_HIDE)
    with pytest.raises(AuditOverlayError, match="only their own"):
        store.edit(actor="X", record_id="m", action=ACTION_HIDE)


def test_edit_history_is_hash_chained_and_append_only() -> None:
    store = _store_with("audit_trail")
    a = store.edit(actor="META", record_id="meta-audit_trail", action=ACTION_HIDE, created_at=2.0)
    b = store.edit(actor="META", record_id="meta-audit_trail", action=ACTION_RESTORE, created_at=3.0)

    assert a.previous_action_sha256 is None
    assert b.previous_action_sha256 == a.action_sha256
    assert store.edit_history == (a, b)
