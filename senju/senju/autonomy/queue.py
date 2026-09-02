"""Persistent work queue and autonomous scheduler for Senju."""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class WorkItemStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


_ALLOWED_AUTHORITY_SCOPES = {
    "none",
    "threat_intel_public",
    "canary_telemetry",
    "github_metadata",
}

_ALLOWED_CATEGORIES = {
    "combat_tactics",
    "evolution_rate",
    "threat_intel",
    "resilience",
    "test",
    "security",
    "defense",
    "red_team",
    "blue_team",
    "research",
    "benchmark",
}


def _has_control(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _bounded_number(value: object, *, field_name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{field_name} must be between {low} and {high}")
    return number


def _bounded_int(value: object, *, field_name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{field_name} must be between {low} and {high}")
    return value


@dataclasses.dataclass
class WorkItem:
    item_id: str
    hypothesis: str
    category: str
    expected_value: float
    cost_budget_matches: int = 400
    runtime_seconds_budget: float = 30.0
    prerequisite_evidence: list[str] = dataclasses.field(default_factory=list)
    status: str = WorkItemStatus.PENDING.value
    attempt_count: int = 0
    max_retries: int = 2
    authority_scope: str = "none"
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    result_reference: str = ""
    blocker_reason: str = ""
    created_at_utc: str = dataclasses.field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat()
    )
    completed_at_utc: str = ""

    def __post_init__(self) -> None:
        for field_name in ("item_id", "hypothesis", "category"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            if _has_control(value):
                raise ValueError(f"{field_name} must not contain control characters")

        if self.category not in _ALLOWED_CATEGORIES:
            raise ValueError(f"unknown work item category: {self.category!r}")

        _bounded_number(self.expected_value, field_name="expected_value", low=0.0, high=1.0)
        _bounded_int(
            self.cost_budget_matches,
            field_name="cost_budget_matches",
            low=1,
            high=5000,
        )
        _bounded_number(
            self.runtime_seconds_budget,
            field_name="runtime_seconds_budget",
            low=0.1,
            high=600.0,
        )
        _bounded_int(self.max_retries, field_name="max_retries", low=0, high=10)
        _bounded_int(self.attempt_count, field_name="attempt_count", low=0, high=1000)

        if self.status not in {status.value for status in WorkItemStatus}:
            raise ValueError(f"unknown work item status: {self.status!r}")
        if not isinstance(self.authority_scope, str) or self.authority_scope not in _ALLOWED_AUTHORITY_SCOPES:
            raise ValueError(f"unknown authority_scope: {self.authority_scope!r}")
        if not isinstance(self.parameters, dict):
            raise ValueError("parameters must be an object")
        if not isinstance(self.prerequisite_evidence, list) or any(
            not isinstance(item, str) for item in self.prerequisite_evidence
        ):
            raise ValueError("prerequisite_evidence must be a list of strings")

        resource_bounds = {
            "population": (2, 256),
            "generations": (1, 100),
            "matches": (1, 5000),
        }
        for name, (low, high) in resource_bounds.items():
            if name in self.parameters:
                _bounded_int(self.parameters[name], field_name=f"parameters.{name}", low=low, high=high)
        if "mutation_rate" in self.parameters:
            _bounded_number(
                self.parameters["mutation_rate"],
                field_name="parameters.mutation_rate",
                low=0.0,
                high=1.0,
            )

    @property
    def deduplication_key(self) -> str:
        """Deterministic fingerprint of hypothesis and parameters."""
        raw = f"{self.hypothesis.strip().lower()}:{json.dumps(self.parameters, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def priority_score(self) -> float:
        """Priority calculated as expected value over cost with retry penalty."""
        cost = max(10, self.cost_budget_matches)
        retry_penalty = 1.0 / (1.0 + self.attempt_count)
        return round((self.expected_value / (cost ** 0.5)) * retry_penalty * 100.0, 4)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkItem":
        if not isinstance(data, dict):
            raise ValueError("work item payload must be an object")
        return cls(**data)


class AutonomyQueue:
    """Durable file-backed queue for bounded autonomous Senju experiments."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._items: dict[str, WorkItem] = {}
        self.load()

    def load(self) -> None:
        if not self.storage_path.exists():
            self._items = {}
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                raise ValueError("queue file must contain an items list")
            self._items = {
                item_data["item_id"]: WorkItem.from_dict(item_data)
                for item_data in data.get("items", [])
            }
        except Exception:
            # Corrupt or invalid persisted input is never executed. The engine will seed
            # a fresh bounded queue on initialization rather than trusting bad state.
            self._items = {}

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "items": [item.to_dict() for item in self._items.values()],
        }
        self.storage_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def enqueue(self, item: WorkItem) -> bool:
        """Enqueue a work item with automatic deduplication against existing items."""
        if not isinstance(item, WorkItem):
            raise TypeError("item must be a WorkItem")
        item.__post_init__()
        dedup = item.deduplication_key
        for existing in self._items.values():
            if existing.deduplication_key == dedup and existing.status in {
                WorkItemStatus.PENDING.value,
                WorkItemStatus.IN_PROGRESS.value,
                WorkItemStatus.COMPLETED.value,
            }:
                return False
        self._items[item.item_id] = item
        self.save()
        return True

    def select_next(self, budget_matches: int = 5000) -> WorkItem | None:
        """Select the highest-priority pending or transient-failed item within budget."""
        _bounded_int(budget_matches, field_name="budget_matches", low=1, high=5000)
        candidates = [
            item for item in self._items.values()
            if item.status in {WorkItemStatus.PENDING.value, WorkItemStatus.FAILED.value}
            and item.attempt_count <= item.max_retries
            and item.cost_budget_matches <= budget_matches
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda it: (-it.priority_score, it.created_at_utc, it.item_id))
        selected = candidates[0]
        selected.status = WorkItemStatus.IN_PROGRESS.value
        selected.attempt_count += 1
        self.save()
        return selected

    def record_result(
        self,
        item_id: str,
        *,
        success: bool,
        result_ref: str = "",
        blocker_reason: str = "",
    ) -> None:
        """Record the outcome of a work item execution."""
        item = self._items.get(item_id)
        if not item:
            return
        if success:
            item.status = WorkItemStatus.COMPLETED.value
            item.result_reference = result_ref
            item.completed_at_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        else:
            if item.attempt_count > item.max_retries:
                item.status = WorkItemStatus.BLOCKED.value
                item.blocker_reason = blocker_reason or "Exceeded maximum retry attempts"
            else:
                item.status = WorkItemStatus.FAILED.value
                item.blocker_reason = blocker_reason
        self.save()

    def pending_count(self) -> int:
        return sum(1 for it in self._items.values() if it.status == WorkItemStatus.PENDING.value)

    def completed_count(self) -> int:
        return sum(1 for it in self._items.values() if it.status == WorkItemStatus.COMPLETED.value)
