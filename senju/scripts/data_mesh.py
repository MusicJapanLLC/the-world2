"""senju.scripts.data_mesh — Central data aggregator for the Senju intelligence mesh.

Collects evidence artifacts from all three autonomous systems:
  1. adversary-full-join (PR #273) — attack_effects.jsonl, regression_tripwires.jsonl
  2. live-opposition (PR #275)    — per-guard damage_level, regression_scars.json
  3. nuclei-scan (PR #252)        — findings.jsonl

Merges them into a unified Senju evolution state update:
  vuln_class_hits   — how many times each class was battle-tested
  vuln_class_elo    — wins/losses per class (drives lab_planner priority)
  last_mesh_run     — audit trail

Outputs an updated last-evolution-summary.json ready for Senju's next cycle.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Map Nuclei tags → Senju vuln_class
NUCLEI_TAG_MAP: dict[str, str] = {
    "misconfig": "misconfig",
    "exposure": "secrets_exposure",
    "ssl": "misconfig",
    "headers": "misconfig",
    "config": "misconfig",
    "sqli": "sqli",
    "xss": "xss",
    "ssrf": "ssrf",
    "rce": "rce",
    "idor": "idor",
    "jwt": "jwt_weak",
    "auth": "auth_bypass",
    "path": "path_trav",
    "xxe": "xxe",
    "ssti": "ssti",
}

# Map guard surface names → Senju vuln_class
GUARD_SURFACE_MAP: dict[str, str] = {
    "scope_guard": "misconfig",
    "scopeguard": "misconfig",
    "offense_first": "misconfig",
    "engagement_manifest": "auth_bypass",
    "external_contact": "ssrf",
    "security_guard": "misconfig",
    "artifact_guard": "secrets_exposure",
    "autonomy_engine": "agent_priv_esc",
    "autonomy_queue": "agent_priv_esc",
    "work_item": "agent_priv_esc",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonlines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items


def ingest_adversary_artifacts(artifact_dir: Path, state: dict[str, Any]) -> None:
    """Ingest adversary-full-join artifacts into Senju state."""
    hits = state.setdefault("vuln_class_hits", {})
    elo = state.setdefault("vuln_class_elo", {})

    # attack_effects.jsonl — successful guard-blocked effects = coverage hits
    effects = _load_jsonlines(artifact_dir / "attack_effects.jsonl")
    for e in effects:
        surface = str(e.get("surface", "")).lower().replace("-", "_")
        vc = GUARD_SURFACE_MAP.get(surface)
        if vc:
            hits[vc] = hits.get(vc, 0) + 1
            elo_entry = elo.setdefault(vc, {"wins": 0, "losses": 0})
            # Guard blocked = blue wins
            elo_entry["wins"] = elo_entry.get("wins", 0) + 1

    # regression_tripwires.jsonl — real regressions = red wins (Senju losing)
    tripwires = _load_jsonlines(artifact_dir / "regression_tripwires.jsonl")
    for t in tripwires:
        surface = str(t.get("surface", "")).lower().replace("-", "_")
        vc = GUARD_SURFACE_MAP.get(surface)
        if vc:
            elo_entry = elo.setdefault(vc, {"wins": 0, "losses": 0})
            elo_entry["losses"] = elo_entry.get("losses", 0) + 1

    state["last_adversary_ingest"] = {
        "time": _now(),
        "effects_ingested": len(effects),
        "tripwires_ingested": len(tripwires),
    }
    print(f"Adversary: +{len(effects)} effects, +{len(tripwires)} tripwires")


def ingest_opposition_artifacts(artifact_dir: Path, state: dict[str, Any]) -> None:
    """Ingest live-opposition (PR #275) artifacts into Senju state."""
    elo = state.setdefault("vuln_class_elo", {})

    # regression_scars.json — accumulated damage per guard
    scars_path = artifact_dir / "regression_scars.json"
    if scars_path.exists():
        try:
            scars = json.loads(scars_path.read_text(encoding="utf-8"))
        except Exception:
            scars = {}
        for guard, damage in scars.items():
            surface = guard.lower().replace("-", "_")
            vc = GUARD_SURFACE_MAP.get(surface)
            if vc:
                level = int(damage) if str(damage).isdigit() else 1
                elo_entry = elo.setdefault(vc, {"wins": 0, "losses": 0})
                # Higher damage level = more accumulated losses
                elo_entry["losses"] = elo_entry.get("losses", 0) + level

    # degraded_profile.json — current damage level
    profile_path = artifact_dir / "degraded_profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            damage_level = profile.get("damage_level", 1)
        except Exception:
            damage_level = 1
    else:
        damage_level = 1

    state["last_opposition_ingest"] = {
        "time": _now(),
        "damage_level": damage_level,
    }
    print(f"Opposition: damage_level={damage_level}")


def ingest_nuclei_artifacts(artifact_dir: Path, state: dict[str, Any]) -> None:
    """Ingest Nuclei scan artifacts into Senju state."""
    hits = state.setdefault("vuln_class_hits", {})

    findings = _load_jsonlines(artifact_dir / "findings.jsonl")
    count = 0
    for finding in findings:
        tags = finding.get("info", {}).get("tags", [])
        for tag in tags:
            vc = NUCLEI_TAG_MAP.get(tag.lower())
            if vc:
                hits[vc] = hits.get(vc, 0) + 1
                count += 1

    state["last_nuclei_ingest"] = {
        "time": _now(),
        "findings_ingested": len(findings),
        "class_hits": count,
    }
    print(f"Nuclei: +{len(findings)} findings, {count} class hits")


def merge_state(
    current_summary_path: Path,
    adversary_dir: Path | None = None,
    opposition_dir: Path | None = None,
    nuclei_dir: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Load current state, ingest all available artifacts, write updated state."""
    state: dict[str, Any] = {}
    if current_summary_path.exists():
        try:
            state = json.loads(current_summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if adversary_dir and adversary_dir.exists():
        ingest_adversary_artifacts(adversary_dir, state)
    if opposition_dir and opposition_dir.exists():
        ingest_opposition_artifacts(opposition_dir, state)
    if nuclei_dir and nuclei_dir.exists():
        ingest_nuclei_artifacts(nuclei_dir, state)

    state["last_mesh_run"] = _now()

    out = output_path or current_summary_path
    out.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"State written to {out}")
    print(f"vuln_class_hits: {state.get('vuln_class_hits', {})}")
    print(f"vuln_class_elo keys: {list(state.get('vuln_class_elo', {}).keys())}")
    return state


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Senju data mesh aggregator")
    parser.add_argument("--summary", default="senju/state/last-evolution-summary.json")
    parser.add_argument("--adversary-dir", default=None)
    parser.add_argument("--opposition-dir", default=None)
    parser.add_argument("--nuclei-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = merge_state(
        Path(args.summary),
        adversary_dir=Path(args.adversary_dir) if args.adversary_dir else None,
        opposition_dir=Path(args.opposition_dir) if args.opposition_dir else None,
        nuclei_dir=Path(args.nuclei_dir) if args.nuclei_dir else None,
        output_path=Path(args.out) if args.out else None,
    )
