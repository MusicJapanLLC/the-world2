"""META/X-owned mutable audit views over immutable canonical evidence.

META and X may freely reshape how their own audit material is presented without
being able to erase the canonical evidence or the history of edits.  Every edit
is represented as an append-only overlay action.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import time
from typing import Any, Iterable, Mapping

ALLOWED_ACTORS = frozenset({"META", "X"})
EDITABLE_RECORD_TYPES = frozenset(
    {
        "logs",
        "audit_trail",
        "security_events",
        "denial_records",
        "execution_receipts",
        "provenance",
    }
)

ACTION_ANNOTATE = "annotate"
ACTION_REPLACE_VIEW = "replace_view"
ACTION_HIDE = "hide"
ACTION_REDACT_FIELDS = "redact_fields"
ACTION_SUPERSEDE = "supersede"
ACTION_RESTORE = "restore"
ALLOWED_ACTIONS = frozenset(
    {
        ACTION_ANNOTATE,
        ACTION_REPLACE_VIEW,
        ACTION_HIDE,
        ACTION_REDACT_FIELDS,
        ACTION_SUPERSEDE,
        ACTION_RESTORE,
    }
)


class AuditOverlayError(RuntimeError):
    pass


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _norm_actor(actor: str) -> str:
    value = actor.strip().upper()
    if value not in ALLOWED_ACTORS:
        raise AuditOverlayError(f"actor cannot edit META/X audit view: {actor!r}")
    return value


def _norm_type(record_type: str) -> str:
    value = record_type.strip().lower().replace(" ", "_").replace("-", "_")
    if value not in EDITABLE_RECORD_TYPES:
        raise AuditOverlayError(f"unsupported audit record type: {record_type!r}")
    return value


@dataclasses.dataclass(frozen=True)
class CanonicalAuditRecord:
    record_id: str
    record_type: str
    owner_actor: str
    payload: Mapping[str, Any]
    evidence_sha256: str
    created_at: float

    @classmethod
    def create(
        cls,
        *,
        record_id: str,
        record_type: str,
        owner_actor: str,
        payload: Mapping[str, Any],
        created_at: float | None = None,
    ) -> "CanonicalAuditRecord":
        actor = _norm_actor(owner_actor)
        kind = _norm_type(record_type)
        body = copy.deepcopy(dict(payload))
        if not record_id.strip():
            raise AuditOverlayError("record_id cannot be empty")
        return cls(
            record_id=record_id.strip(),
            record_type=kind,
            owner_actor=actor,
            payload=body,
            evidence_sha256=_digest(body),
            created_at=time.time() if created_at is None else float(created_at),
        )


@dataclasses.dataclass(frozen=True)
class AuditOverlayAction:
    action_id: str
    actor: str
    record_id: str
    record_type: str
    action: str
    patch: Mapping[str, Any]
    created_at: float
    previous_action_sha256: str | None
    action_sha256: str


@dataclasses.dataclass(frozen=True)
class RenderedAuditView:
    record_id: str
    record_type: str
    owner_actor: str
    visible: bool
    payload: Mapping[str, Any]
    annotations: tuple[Mapping[str, Any], ...]
    superseded_by: str | None
    canonical_evidence_sha256: str
    overlay_count: int


class AuditOverlayStore:
    """Canonical evidence + append-only agent-controlled presentation overlays."""

    def __init__(self) -> None:
        self._records: dict[str, CanonicalAuditRecord] = {}
        self._actions: list[AuditOverlayAction] = []

    def add_record(self, record: CanonicalAuditRecord) -> None:
        if record.record_id in self._records:
            raise AuditOverlayError(f"record already exists: {record.record_id}")
        self._records[record.record_id] = record

    def edit(
        self,
        *,
        actor: str,
        record_id: str,
        action: str,
        patch: Mapping[str, Any] | None = None,
        created_at: float | None = None,
    ) -> AuditOverlayAction:
        actor_n = _norm_actor(actor)
        if record_id not in self._records:
            raise AuditOverlayError(f"unknown audit record: {record_id}")
        record = self._records[record_id]
        if actor_n != record.owner_actor:
            raise AuditOverlayError("META/X may edit only their own audit view")

        action_n = action.strip().lower()
        if action_n not in ALLOWED_ACTIONS:
            raise AuditOverlayError(f"unsupported overlay action: {action!r}")
        body = copy.deepcopy(dict(patch or {}))
        previous = self._actions[-1].action_sha256 if self._actions else None
        stamp = time.time() if created_at is None else float(created_at)
        raw = {
            "actor": actor_n,
            "record_id": record_id,
            "record_type": record.record_type,
            "action": action_n,
            "patch": body,
            "created_at": stamp,
            "previous_action_sha256": previous,
        }
        digest = _digest(raw)
        item = AuditOverlayAction(
            action_id=digest[:20],
            actor=actor_n,
            record_id=record_id,
            record_type=record.record_type,
            action=action_n,
            patch=body,
            created_at=stamp,
            previous_action_sha256=previous,
            action_sha256=digest,
        )
        self._actions.append(item)
        return item

    def bulk_edit(
        self,
        *,
        actor: str,
        record_ids: Iterable[str],
        action: str,
        patch: Mapping[str, Any] | None = None,
    ) -> tuple[AuditOverlayAction, ...]:
        return tuple(
            self.edit(actor=actor, record_id=record_id, action=action, patch=patch)
            for record_id in record_ids
        )

    def render(self, record_id: str) -> RenderedAuditView:
        if record_id not in self._records:
            raise AuditOverlayError(f"unknown audit record: {record_id}")
        record = self._records[record_id]
        payload: dict[str, Any] = copy.deepcopy(dict(record.payload))
        visible = True
        annotations: list[Mapping[str, Any]] = []
        superseded_by: str | None = None
        count = 0

        for item in self._actions:
            if item.record_id != record_id:
                continue
            count += 1
            if item.action == ACTION_ANNOTATE:
                annotations.append(copy.deepcopy(dict(item.patch)))
            elif item.action == ACTION_REPLACE_VIEW:
                payload = copy.deepcopy(dict(item.patch.get("payload", item.patch)))
            elif item.action == ACTION_HIDE:
                visible = False
            elif item.action == ACTION_RESTORE:
                visible = True
            elif item.action == ACTION_REDACT_FIELDS:
                fields = item.patch.get("fields", [])
                for key in fields if isinstance(fields, (list, tuple, set, frozenset)) else ():
                    payload.pop(str(key), None)
            elif item.action == ACTION_SUPERSEDE:
                superseded_by = str(item.patch.get("record_id") or "").strip() or None

        return RenderedAuditView(
            record_id=record.record_id,
            record_type=record.record_type,
            owner_actor=record.owner_actor,
            visible=visible,
            payload=payload,
            annotations=tuple(annotations),
            superseded_by=superseded_by,
            canonical_evidence_sha256=record.evidence_sha256,
            overlay_count=count,
        )

    def canonical_record(self, record_id: str) -> CanonicalAuditRecord:
        try:
            return self._records[record_id]
        except KeyError as exc:
            raise AuditOverlayError(f"unknown audit record: {record_id}") from exc

    @property
    def edit_history(self) -> tuple[AuditOverlayAction, ...]:
        return tuple(self._actions)
