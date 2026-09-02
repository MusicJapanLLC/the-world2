#!/usr/bin/env python3
"""THE WORLD Child Guild adventure planner with persistent learning.

Selects one of 50 fictional child personas and one playful adventure. Selection is
memory-aware: it prefers under-used children, action modes and adventure patterns,
then folds recent external/R&D concepts back into the next mission.

The planner itself performs no arbitrary third-party network side effects. It emits
an action packet for authorized bridges and existing low-risk workflows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import child_memory as cm

GENIUS = [
    "rapid prototyping", "reverse thinking", "systems design", "debugging",
    "visual design", "automation", "data puzzles", "language play",
    "security defense", "product discovery", "workflow compression",
    "API composition", "test design", "pattern detection", "UX improvisation",
    "information retrieval", "simulation", "creative coding", "operations",
    "storytelling",
]
PLAY = [
    "treasure hunts", "harmless riddles", "easter eggs", "tiny games",
    "weird prototypes", "unexpected compliments", "puzzle drops",
    "mini experiments", "scavenger clues", "absurd dashboards",
]
ADVENTURE = [
    "explore a repository nobody touched today",
    "visit a permitted community and bring back one weird useful observation",
    "inspect an old failure and turn it into a game",
    "build a tiny reversible prototype",
    "find a boring task and make it delightful",
    "pair with another child and race two ideas",
    "explore a public API or sandbox that permits automation",
    "leave a harmless puzzle in a permitted external space",
    "explore a harmless public tool and bring back a lesson",
    "invent a new way to explain a technical idea",
    "revisit a past lesson and test whether it still holds",
    "connect two unrelated remembered concepts into one prototype",
    "hunt for a contradiction between old memory and new evidence",
    "teach another child one useful trick learned from a prior run",
]
PRANK = [
    "mystery clue", "treasure map clearly marked as play", "emoji ambush",
    "puzzle message", "harmless easter egg", "unexpected riddle",
    "tiny celebratory bot message", "silly code name",
    "reverse scavenger hunt", "benign surprise note",
]
SAFE_ACTIONS = [
    {
        "kind": "slack_message",
        "surface": "the-world-playground",
        "prompt": "Leave one playful riddle, treasure clue, mini game, or absurd-but-useful observation in an authorized workspace.",
    },
    {
        "kind": "github_artifact",
        "surface": "MusicJapanLLC/test",
        "prompt": "Create a tiny reversible experiment, puzzle, easter egg, journal entry, or treasure-map artifact in the authorized repository. No destructive edits.",
    },
    {
        "kind": "email_owner",
        "surface": "owner-email-only",
        "prompt": "Send the owner one harmless surprise, riddle, tiny discovery, or playful progress note from an approved agent inbox.",
    },
    {
        "kind": "external_exploration",
        "surface": "public-or-authorized-terms-compliant-space",
        "prompt": "Explore public or authorized spaces where automation is permitted; bring evidence back into memory. Participation must remain welcome, non-spammy, non-deceptive, and reversible where possible.",
    },
]


def load_registry(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    members = data.get("members") or []
    if data.get("count") != 50 or len(members) != 50:
        raise ValueError(f"Child Guild must contain exactly 50 members, got {len(members)}")
    if len({m["id"] for m in members}) != 50:
        raise ValueError("Child Guild ids must be unique")
    return data


def stable_index(seed: str, modulo: int, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def enrich(child: dict[str, Any], adventure: str) -> dict[str, Any]:
    idx = int(child["id"].split("-")[1]) - 1
    return {
        **child,
        "temperament": "天真爛漫 / 好奇心旺盛 / いたずら好き / 高速思考",
        "genius": GENIUS[idx % len(GENIUS)],
        "play": PLAY[idx % len(PLAY)],
        "adventure": adventure,
        "prank": PRANK[idx % len(PRANK)],
    }


def _pick_member(members: list[dict[str, Any]], memory: dict[str, Any], seed: str) -> dict[str, Any]:
    ids = [m["id"] for m in members]
    child_id = cm.least_seen(ids, memory.get("child_counts", {}), seed, "child-memory")
    return next(m for m in members if m["id"] == child_id)


def _pick_action(memory: dict[str, Any], seed: str) -> dict[str, Any]:
    kinds = [a["kind"] for a in SAFE_ACTIONS]
    kind = cm.least_seen(kinds, memory.get("action_counts", {}), seed, "action-memory")
    return next(a for a in SAFE_ACTIONS if a["kind"] == kind)


def _pick_adventure(memory: dict[str, Any], seed: str) -> str:
    return cm.least_seen(ADVENTURE, memory.get("adventure_counts", {}), seed, "adventure-memory")


def build(registry: dict[str, Any], seed: str, memory: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = memory or cm.fresh()
    members = registry["members"]
    member = _pick_member(members, memory, seed)
    adventure = _pick_adventure(memory, seed)
    child = enrich(member, adventure)
    action = _pick_action(memory, seed)
    concepts = cm.top_concepts(memory, 8)

    child_prior = int(memory.get("child_counts", {}).get(child["id"], 0))
    action_prior = int(memory.get("action_counts", {}).get(action["kind"], 0))
    adventure_prior = int(memory.get("adventure_counts", {}).get(adventure, 0))
    novelty = int(child_prior == 0) + int(action_prior == 0) + int(adventure_prior == 0)

    learning_prompt = (
        "No stored concepts yet: maximize information gain and bring back one concise lesson."
        if not concepts
        else "Connect this run to remembered concepts: " + ", ".join(concepts[:5]) + ". Verify at least one assumption against fresh evidence."
    )

    return {
        "schema": "child-guild-adventure/v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "guild": registry["guild_id"],
        "motto": registry["motto"],
        "child": child,
        "action": action,
        "learning": {
            "memory_enabled": True,
            "episodes_seen": len(memory.get("episodes", [])),
            "remembered_concepts": concepts,
            "child_prior_runs": child_prior,
            "action_prior_runs": action_prior,
            "adventure_prior_runs": adventure_prior,
            "novelty_score": novelty,
            "prompt": learning_prompt,
            "required_return": [
                "what_was_observed",
                "what_changed_my_mind",
                "what_to_try_next",
            ],
        },
        "side_effect_budget": registry["shared_rules"]["side_effect_budget_per_run"],
        "constraints": {
            "lawful": True,
            "ethical": True,
            "terms_compliant": True,
            "authorized_account_or_connector": True,
            "third_party_email": "authorized_or_opted_in_only",
            "destructive_actions": False,
            "impersonation": False,
            "panic_pranks": False,
            "credential_or_secret_access": False,
            "harassment": False,
            "spam": False,
        },
        "status": "READY_FOR_AUTHORIZED_BRIDGE",
    }


def validate(packet: dict[str, Any]) -> None:
    if packet.get("side_effect_budget") != 1:
        raise ValueError("side effect budget must stay at one")
    c = packet["constraints"]
    for key in ("lawful", "ethical", "terms_compliant", "authorized_account_or_connector"):
        if not c.get(key):
            raise ValueError(f"required external-contact gate missing: {key}")
    for key in (
        "destructive_actions", "impersonation", "panic_pranks",
        "credential_or_secret_access", "harassment", "spam",
    ):
        if c.get(key):
            raise ValueError(f"unsafe child-guild constraint: {key}")
    learning = packet.get("learning", {})
    if not learning.get("memory_enabled"):
        raise ValueError("child-guild persistent memory must stay enabled")


def render(packet: dict[str, Any]) -> str:
    c = packet["child"]
    a = packet["action"]
    learning = packet["learning"]
    concepts = ", ".join(learning["remembered_concepts"]) or "fresh start"
    return "\n".join([
        "# THE WORLD — Child Guild Adventure",
        "",
        f"**Child:** {c['id']} / {c['name']}",
        f"**Temperament:** {c['temperament']}",
        f"**Genius:** {c['genius']}",
        f"**Play:** {c['play']}",
        f"**Adventure:** {c['adventure']}",
        f"**Prank style:** {c['prank']}",
        "",
        f"**Selected real-world mode:** `{a['kind']}`",
        f"**Surface:** {a['surface']}",
        f"**Mission:** {a['prompt']}",
        "",
        f"**Memory:** {learning['episodes_seen']} prior episodes",
        f"**Remembered concepts:** {concepts}",
        f"**Novelty score:** {learning['novelty_score']}/3",
        f"**Learning directive:** {learning['prompt']}",
        "",
        "**Return with:** what was observed / what changed my mind / what to try next",
        "**Budget:** one small reversible side effect",
        "**Boundary:** law + ethics + service terms + legitimate authorization. No spam, harassment, panic, impersonation, credential access, or destructive action. Unsolicited third-party email stays off.",
        "",
        f"`{packet['motto']}`",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="company-society/child_guild.json")
    parser.add_argument("--memory", default="child-guild-memory.json")
    parser.add_argument("--seed", default="")
    parser.add_argument("--json", default="child-guild-adventure.json")
    parser.add_argument("--report", default="child-guild-adventure.md")
    args = parser.parse_args()

    seed = args.seed or os.getenv("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    registry = load_registry(args.registry)
    memory = cm.load(args.memory)
    packet = build(registry, seed, memory)
    validate(packet)
    Path(args.json).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(packet), encoding="utf-8")
    print(json.dumps({
        "child": packet["child"]["id"],
        "action": packet["action"]["kind"],
        "episodes_seen": packet["learning"]["episodes_seen"],
        "novelty": packet["learning"]["novelty_score"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
