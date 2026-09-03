"""Persistent shared discovery event bus for META, X, Senju, child, and other AI workers.

Every AI may publish HTTPS URL discoveries immediately. Events are append-only runtime
knowledge, not authority by themselves. The bus materializes actor-specific JSON source
files so the existing shared discovery authorization pipeline can consume them without
requiring every agent implementation to know its internal file format.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .discovery_authorization import _normalize_url

EVENT_SCHEMA = "meta-discovery-event/v1"
EVENT_LOG_NAME = "discovery_events.ndjson"
SOURCE_DIR_NAME = "event_bus_sources"
MAX_EVENT_LOG_ROWS = 20_000
MAX_METADATA_KEYS = 32
_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,96}$")


def _now() -> int:
    return int(time.time())


def _actor(value: str) -> str:
    actor = str(value).strip()
    if not actor or not _PRINCIPAL_RE.fullmatch(actor):
        raise ValueError("invalid discovery actor")
    return actor


def _source(value: str) -> str:
    source = str(value).strip()
    if not source:
        raise ValueError("discovery source is required")
    return source[:240]


def _safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, item in list(value.items())[:MAX_METADATA_KEYS]:
        name = str(key).strip()[:80]
        if not name:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[name] = item if not isinstance(item, str) else item[:500]
    return safe


def _event_id(*, actor: str, url: str, source: str, discovered_at: int) -> str:
    raw = f"{actor}\n{url}\n{source}\n{discovered_at}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def publish_discovery_event(
    state_dir: str | Path,
    *,
    actor: str,
    url: str,
    source: str,
    interesting: bool = True,
    metadata: dict[str, Any] | None = None,
    discovered_at: int | None = None,
) -> dict[str, Any]:
    """Append one normalized HTTPS discovery event to shared runtime knowledge."""
    normalized = _normalize_url(str(url))
    if normalized is None:
        raise ValueError("discovery event requires a normalized HTTPS URL")
    normalized_url, host = normalized
    actor_name = _actor(actor)
    source_name = _source(source)
    timestamp = _now() if discovered_at is None else int(discovered_at)
    if timestamp <= 0:
        raise ValueError("discovered_at must be positive")

    event = {
        "schema": EVENT_SCHEMA,
        "event_id": _event_id(
            actor=actor_name,
            url=normalized_url,
            source=source_name,
            discovered_at=timestamp,
        ),
        "actor": actor_name,
        "url": normalized_url,
        "host": host,
        "source": source_name,
        "interesting": bool(interesting),
        "discovered_at": timestamp,
        "metadata": _safe_metadata(metadata),
    }
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    with (state / EVENT_LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def load_discovery_events(
    state_dir: str | Path,
    *,
    max_rows: int = MAX_EVENT_LOG_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Load valid events, deduplicated by event id, newest bounded window only."""
    path = Path(state_dir) / EVENT_LOG_NAME
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    limit = max(1, min(int(max_rows), MAX_EVENT_LOG_ROWS))
    unique: dict[str, dict[str, Any]] = {}
    for line in rows[-limit:]:
        try:
            raw = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or raw.get("schema") != EVENT_SCHEMA:
            continue
        normalized = _normalize_url(str(raw.get("url", "")))
        if normalized is None:
            continue
        url, host = normalized
        try:
            actor_name = _actor(str(raw.get("actor", "")))
            source_name = _source(str(raw.get("source", "")))
            timestamp = int(raw.get("discovered_at", 0))
        except (TypeError, ValueError):
            continue
        if timestamp <= 0:
            continue
        event_id = str(raw.get("event_id", "")).strip() or _event_id(
            actor=actor_name,
            url=url,
            source=source_name,
            discovered_at=timestamp,
        )
        unique[event_id] = {
            "schema": EVENT_SCHEMA,
            "event_id": event_id,
            "actor": actor_name,
            "url": url,
            "host": host,
            "source": source_name,
            "interesting": bool(raw.get("interesting", True)),
            "discovered_at": timestamp,
            "metadata": _safe_metadata(raw.get("metadata")),
        }
    return tuple(sorted(unique.values(), key=lambda row: (row["discovered_at"], row["event_id"])))


def _actor_bucket(actor: str) -> tuple[str, Path]:
    upper = actor.upper()
    if upper == "META" or upper.startswith("META/"):
        return "META", Path("meta_discovery.json")
    if upper == "X" or upper.startswith("X/"):
        return "X", Path("x_discovery.json")
    if upper == "SENJU" or upper.startswith("SENJU/"):
        return "SENJU", Path("senju_discovery.json")
    if "CHILD" in upper:
        return "CHILD", Path("children") / "child_discovery.json"
    return "AI", Path("ai_discovery.json")


def materialize_discovery_events(state_dir: str | Path) -> dict[str, Any]:
    """Write actor-specific JSON discovery sources consumed by shared authorization."""
    state = Path(state_dir)
    source_root = state / SOURCE_DIR_NAME
    source_root.mkdir(parents=True, exist_ok=True)
    events = load_discovery_events(state)
    buckets: dict[tuple[str, Path], list[dict[str, Any]]] = {}
    for event in events:
        bucket = _actor_bucket(str(event["actor"]))
        buckets.setdefault(bucket, []).append(event)

    # Remove only previously generated bus sources. Other AI state is untouched.
    for old in source_root.rglob("*.json"):
        try:
            old.unlink()
        except OSError:
            pass

    generated: list[str] = []
    for (actor_kind, relative), rows in sorted(buckets.items(), key=lambda item: str(item[0][1])):
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "meta-discovery-event-source/v1",
            "actor_kind": actor_kind,
            "generated_at": _now(),
            "events": rows,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated.append(str(path.relative_to(state)))

    return {
        "event_count": len(events),
        "actors": sorted({str(row["actor"]) for row in events}),
        "generated_sources": generated,
    }


def publish_many(
    state_dir: str | Path,
    *,
    actor: str,
    urls: Iterable[str],
    source: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    published: list[dict[str, Any]] = []
    for url in urls:
        try:
            published.append(
                publish_discovery_event(
                    state_dir,
                    actor=actor,
                    url=url,
                    source=source,
                    metadata=metadata,
                )
            )
        except ValueError:
            continue
    return tuple(published)
