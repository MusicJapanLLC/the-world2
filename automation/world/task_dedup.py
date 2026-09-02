#!/usr/bin/env python3
"""Task deduplication for THE WORLD.

Generates deterministic task keys to prevent redundant subagents, duplicate
branches, and issue/PR spam.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATE_FILE = Path("automation/world/task_dedup_state.json")


def compute_task_key(task_type: str, title: str, details: str | dict[str, Any]) -> str:
    raw_details = json.dumps(details, sort_keys=True) if isinstance(details, dict) else str(details)
    normalized = f"{task_type.strip().lower()}:{title.strip().lower()}:{raw_details.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class TaskDeduplicator:
    def __init__(self, state_file: Path = STATE_FILE) -> None:
        self.state_file = state_file
        self.seen_keys: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.seen_keys, indent=2) + "\n", encoding="utf-8")

    def register_or_check(self, task_type: str, title: str, details: Any) -> tuple[bool, str]:
        key = compute_task_key(task_type, title, details)
        if key in self.seen_keys:
            return True, key
        self.seen_keys[key] = {
            "task_type": task_type,
            "title": title,
            "registered_at": json.dumps(str(details)),
        }
        self._save()
        return False, key


if __name__ == "__main__":
    dedup = TaskDeduplicator()
    is_dup, key = dedup.register_or_check("fix", "Memory leak in runner", {"module": "realtime"})
    print(f"Key: {key}, Duplicate: {is_dup}")
