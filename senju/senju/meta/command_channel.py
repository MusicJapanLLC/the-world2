"""META Command Channel — META writes, drive_engine/#273/#275 read."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any


@dataclasses.dataclass
class AttackCommand:
    target_surface: str
    pressure_multiplier: float
    priority: int
    reason: str
    expires_after_cycles: int = 3
    issued_at: str = dataclasses.field(default_factory=lambda: dt.datetime.utcnow().isoformat() + "Z")


@dataclasses.dataclass
class QueueCommand:
    action: str
    target_item_id: str | None
    vuln_classes: list[str]
    reason: str
    issued_at: str = dataclasses.field(default_factory=lambda: dt.datetime.utcnow().isoformat() + "Z")


@dataclasses.dataclass
class MetaCommandSet:
    schema: str = "meta-commands/v1"
    issued_at: str = dataclasses.field(default_factory=lambda: dt.datetime.utcnow().isoformat() + "Z")
    attack_commands: list[AttackCommand] = dataclasses.field(default_factory=list)
    queue_commands: list[QueueCommand] = dataclasses.field(default_factory=list)
    dispatch_targets: list[str] = dataclasses.field(default_factory=list)


def write(command_set: MetaCommandSet, state_dir: Path) -> Path:
    path = state_dir / "meta_commands.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(command_set), ensure_ascii=False, indent=2))
    return path


def read(state_dir: Path) -> MetaCommandSet | None:
    path = state_dir / "meta_commands.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return MetaCommandSet(
            schema=data.get("schema", "meta-commands/v1"),
            issued_at=data.get("issued_at", ""),
            attack_commands=[AttackCommand(**a) for a in data.get("attack_commands", [])],
            queue_commands=[QueueCommand(**q) for q in data.get("queue_commands", [])],
            dispatch_targets=data.get("dispatch_targets", []),
        )
    except Exception:
        return None


def build_from_graph(graph: Any, top_n: int = 3) -> MetaCommandSet:
    cmd = MetaCommandSet()
    for i, (surface, score) in enumerate(list(graph.surface_weakness_scores.items())[:top_n]):
        cmd.attack_commands.append(AttackCommand(
            target_surface=surface,
            pressure_multiplier=min(10.0, 1.0 + score),
            priority=i + 1,
            reason=f"weakness_score={score:.2f} from {len(graph.observations)} observations",
        ))
    for surface_a, co_surfaces in list(graph.co_occurrence.items())[:2]:
        cmd.queue_commands.append(QueueCommand(
            action="boost",
            target_item_id=None,
            vuln_classes=[surface_a] + co_surfaces[:2],
            reason=f"co-regression cluster: {surface_a} ↔ {co_surfaces}",
        ))
    return cmd
