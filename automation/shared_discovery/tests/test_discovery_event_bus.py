from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.discovery_event_bus import (
    load_discovery_events,
    materialize_discovery_events,
    publish_discovery_event,
)


def test_meta_x_senju_child_events_materialize_as_shared_sources(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    publish_discovery_event(state, actor="META", url="https://meta.owner.example/a", source="crawler")
    publish_discovery_event(state, actor="X", url="https://x.owner.example/b", source="external_response")
    publish_discovery_event(state, actor="SENJU", url="https://senju.owner.example/c", source="probe")
    publish_discovery_event(state, actor="CHILD/7", url="https://child.owner.example/d", source="log")

    result = materialize_discovery_events(state)

    assert result["event_count"] == 4
    assert set(result["actors"]) == {"META", "X", "SENJU", "CHILD/7"}
    generated = set(result["generated_sources"])
    assert "event_bus_sources/meta_discovery.json" in generated
    assert "event_bus_sources/x_discovery.json" in generated
    assert "event_bus_sources/senju_discovery.json" in generated
    assert "event_bus_sources/children/child_discovery.json" in generated

    meta = json.loads((state / "event_bus_sources" / "meta_discovery.json").read_text())
    assert meta["actor_kind"] == "META"
    assert meta["events"][0]["url"] == "https://meta.owner.example/a"


def test_event_bus_rejects_non_https_and_embedded_credentials(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    with pytest.raises(ValueError):
        publish_discovery_event(state, actor="META", url="http://owner.example/", source="crawler")
    with pytest.raises(ValueError):
        publish_discovery_event(
            state,
            actor="META",
            url="https://user:pass@owner.example/",
            source="crawler",
        )
    assert load_discovery_events(state) == ()


def test_event_log_is_append_only_and_deduplicates_event_ids(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    first = publish_discovery_event(
        state,
        actor="X",
        url="https://owner.example/a#fragment",
        source="response",
        discovered_at=1234,
    )
    second = publish_discovery_event(
        state,
        actor="X",
        url="https://owner.example/a",
        source="response",
        discovered_at=1234,
    )
    assert first["event_id"] == second["event_id"]
    rows = load_discovery_events(state)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://owner.example/a"
