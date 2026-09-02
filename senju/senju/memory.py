"""Persistent memory for Senju's lab-only evolutionary agents.

Only numerical strategy genomes and aggregate scores are persisted. No target data,
credentials, payloads, or executable attack logic are stored here.
"""
from __future__ import annotations

import dataclasses
import json
import random
from pathlib import Path
from typing import Any

from .agents.base import Agent, BlueGenome, RedGenome

STATE_VERSION = 1


def genome_to_dict(genome: object) -> dict[str, Any]:
    if isinstance(genome, RedGenome):
        return {"kind": "red", **dataclasses.asdict(genome)}
    if isinstance(genome, BlueGenome):
        return {"kind": "blue", **dataclasses.asdict(genome)}
    raise TypeError(f"unsupported genome: {type(genome)!r}")


def _compatible_body(genome_cls: type, body: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields understood by the currently installed genome class.

    Durable champion artifacts can outlive the exact code revision that produced
    them. A newer RED/BLUE generation may therefore contain strategy genes that
    an older checkout does not know yet. Unknown numerical strategy fields must
    not crash the evolution loop; they become active automatically once the
    corresponding dataclass field exists in the running revision.
    """
    known = {field.name for field in dataclasses.fields(genome_cls)}
    return {key: value for key, value in body.items() if key in known}


def genome_from_dict(data: dict[str, Any]) -> RedGenome | BlueGenome:
    kind = data.get("kind")
    body = {k: v for k, v in data.items() if k != "kind"}
    if kind == "red":
        return RedGenome(**_compatible_body(RedGenome, body))
    if kind == "blue":
        return BlueGenome(**_compatible_body(BlueGenome, body))
    raise ValueError(f"invalid genome kind: {kind!r}")


def agent_to_dict(agent: Agent | None) -> dict[str, Any] | None:
    if agent is None:
        return None
    return {
        "side": agent.side,
        "rating": agent.rating,
        "resources": agent.resources,
        "generation": agent.generation,
        "genome": genome_to_dict(agent.genome),
    }


def load_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"version": STATE_VERSION, "history": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError("unsupported Senju memory version")
    return data


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seeded_population(
    champion: dict[str, Any] | None,
    side: str,
    size: int,
    mutation_rate: float,
    rng: random.Random,
) -> list[Agent] | None:
    """Build tomorrow's population around yesterday's champion.

    The exact champion survives as elite; the rest are mutated descendants. Returning
    None means there is no memory yet and the normal random seeding path should run.
    """
    if not champion:
        return None
    base = genome_from_dict(champion["genome"])
    if getattr(base, "__class__") not in (RedGenome, BlueGenome):
        return None
    if (side == "red") != isinstance(base, RedGenome):
        raise ValueError("champion side/genome mismatch")

    pop = [
        Agent(
            genome=base,
            side=side,
            rating=float(champion.get("rating", 1000.0)),
            resources=float(champion.get("resources", 100.0)),
            generation=int(champion.get("generation", 0)) + 1,
        )
    ]
    while len(pop) < size:
        genome = base.mutate(mutation_rate, rng)
        pop.append(
            Agent(
                genome=genome,
                side=side,
                rating=float(champion.get("rating", 1000.0)),
                resources=max(25.0, float(champion.get("resources", 100.0)) / 2.0),
                generation=int(champion.get("generation", 0)) + 1,
            )
        )
    return pop
