#!/usr/bin/env python3
"""Persistent learning memory for THE WORLD Child Guild.

The guild keeps compact, auditable memory across scheduled runs so adventures do
not reset to zero every time. Memory intentionally stores summaries, counters and
concept tokens rather than secrets or raw credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "child-guild-memory/v1"
MAX_EPISODES = 240
MAX_RECENT_CONCEPTS = 80
STOP = {
    "the", "and", "for", "with", "from", "this", "that", "into", "your", "you",
    "are", "was", "were", "have", "has", "had", "not", "but", "can", "will",
    "child", "guild", "world", "http", "https", "json", "true", "false", "none",
}


def fresh() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "updated_at": None,
        "episodes": [],
        "child_counts": {},
        "action_counts": {},
        "adventure_counts": {},
        "genius_counts": {},
        "concept_counts": {},
        "recent_concepts": [],
        "observation_digests": [],
    }


def load(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return fresh()
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        out = fresh()
        for key in ("episodes", "child_counts", "action_counts", "adventure_counts", "genius_counts", "concept_counts", "recent_concepts", "observation_digests"):
            if key in data:
                out[key] = data[key]
        return out
    return data


def save(memory: dict[str, Any], path: str | Path) -> None:
    memory["schema"] = SCHEMA
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    Path(path).write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inc(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = int(mapping.get(key, 0)) + amount


def _fingerprint(packet: dict[str, Any]) -> str:
    child = packet.get("child", {})
    action = packet.get("action", {})
    raw = "|".join([
        str(child.get("id", "")),
        str(child.get("adventure", "")),
        str(child.get("genius", "")),
        str(action.get("kind", "")),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def record_episode(memory: dict[str, Any], packet: dict[str, Any], outcome: str = "planned") -> None:
    child = packet.get("child", {})
    action = packet.get("action", {})
    child_id = str(child.get("id", "unknown"))
    action_kind = str(action.get("kind", "unknown"))
    adventure = str(child.get("adventure", "unknown"))
    genius = str(child.get("genius", "unknown"))

    _inc(memory["child_counts"], child_id)
    _inc(memory["action_counts"], action_kind)
    _inc(memory["adventure_counts"], adventure)
    _inc(memory["genius_counts"], genius)

    memory["episodes"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "child": child_id,
        "name": child.get("name"),
        "action": action_kind,
        "surface": action.get("surface"),
        "adventure": adventure,
        "genius": genius,
        "outcome": outcome,
        "fingerprint": _fingerprint(packet),
    })
    memory["episodes"] = memory["episodes"][-MAX_EPISODES:]


def _iter_text(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"token", "secret", "password", "cookie", "authorization", "api_key", "apikey"}:
                continue
            yield from _iter_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text(item)


def extract_concepts(value: Any, limit: int = 24) -> list[str]:
    text = " ".join(_iter_text(value)).lower()
    tokens = re.findall(r"[a-z][a-z0-9_-]{3,32}|[ぁ-んァ-ン一-龯]{2,12}", text)
    counts = Counter(t for t in tokens if t not in STOP and not t.startswith("ghp_") and not t.startswith("sk_"))
    return [token for token, _ in counts.most_common(limit)]


def ingest_observation(memory: dict[str, Any], value: Any, source: str) -> None:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    seen = set(memory.get("observation_digests", []))
    if digest in seen:
        return

    concepts = extract_concepts(value)
    for concept in concepts:
        _inc(memory["concept_counts"], concept)
    memory["recent_concepts"] = (concepts + list(memory.get("recent_concepts", [])))[:MAX_RECENT_CONCEPTS]
    memory["observation_digests"] = (list(memory.get("observation_digests", [])) + [digest])[-120:]
    memory.setdefault("observations", []).append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "digest": digest,
        "concepts": concepts[:12],
    })
    memory["observations"] = memory["observations"][-120:]


def compact_fleet_observation(fleet: dict[str, Any]) -> dict[str, Any]:
    """Drop raw result URLs/bodies before Child shared memory ingestion."""
    if not isinstance(fleet, dict):
        return {}
    summary = fleet.get("summary") if isinstance(fleet.get("summary"), dict) else {}
    rnd = fleet.get("rnd_capsule") if isinstance(fleet.get("rnd_capsule"), dict) else {}
    return {
        "schema": fleet.get("schema"),
        "fleet_size": fleet.get("fleet_size"),
        "mode": fleet.get("mode"),
        "summary": {
            "status_counts": summary.get("status_counts", {}),
            "distinct_domains": summary.get("distinct_domains", 0),
            "top_concepts": (summary.get("top_concepts") or [])[:20],
            "research_hypotheses": (summary.get("research_hypotheses") or [])[:8],
        },
        "rnd_capsule": {
            "top_concepts": (rnd.get("top_concepts") or [])[:12],
            "hypotheses": (rnd.get("hypotheses") or [])[:6],
        },
    }


def least_seen(keys: list[str], counts: dict[str, int], seed: str, salt: str) -> str:
    if not keys:
        raise ValueError("least_seen requires at least one candidate")
    minimum = min(int(counts.get(k, 0)) for k in keys)
    pool = [k for k in keys if int(counts.get(k, 0)) == minimum]
    digest = hashlib.sha256(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return pool[int(digest[:12], 16) % len(pool)]


def top_concepts(memory: dict[str, Any], limit: int = 8) -> list[str]:
    counts = memory.get("concept_counts", {})
    recent = memory.get("recent_concepts", [])
    score = Counter({k: int(v) for k, v in counts.items()})
    for idx, concept in enumerate(recent[:24]):
        score[concept] += max(1, 6 - idx // 4)
    return [name for name, _ in score.most_common(limit)]


def render(memory: dict[str, Any]) -> str:
    concepts = top_concepts(memory, 10)
    least_children = sorted(memory.get("child_counts", {}).items(), key=lambda kv: (kv[1], kv[0]))[:5]
    return "\n".join([
        "# THE WORLD — Child Guild Memory",
        "",
        f"**Episodes retained:** {len(memory.get('episodes', []))}",
        f"**Distinct observations:** {len(memory.get('observation_digests', []))}",
        f"**Active concepts:** {', '.join(concepts) if concepts else 'none yet'}",
        f"**Least-used children:** {', '.join(f'{k}:{v}' for k, v in least_children) if least_children else 'all fresh'}",
        "",
        "Memory is compact and auditable: counters, digests, concept summaries, and recent episodes only.",
        "Secrets, credentials, cookies, authorization material, and raw private payloads are not intended memory content.",
        "",
    ])


def _read_json_if_exists(path: str | None) -> Any | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", default="child-guild-memory.json")
    parser.add_argument("--packet")
    parser.add_argument("--observation")
    parser.add_argument("--sparks")
    parser.add_argument("--fleet")
    parser.add_argument("--out", default="child-guild-memory.json")
    parser.add_argument("--report", default="child-guild-memory.md")
    args = parser.parse_args()

    memory = load(args.memory)
    packet = _read_json_if_exists(args.packet)
    if packet:
        record_episode(memory, packet)
    observation = _read_json_if_exists(args.observation)
    if observation is not None:
        ingest_observation(memory, observation, "outside-world")
    sparks = _read_json_if_exists(args.sparks)
    if sparks is not None:
        ingest_observation(memory, sparks, "child-research-sparks")
    fleet = _read_json_if_exists(args.fleet)
    if isinstance(fleet, dict):
        compact = compact_fleet_observation(fleet)
        if compact:
            ingest_observation(memory, compact, "child-external-fleet")

    save(memory, args.out)
    Path(args.report).write_text(render(memory), encoding="utf-8")
    print(json.dumps({
        "episodes": len(memory.get("episodes", [])),
        "concepts": top_concepts(memory, 6),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
