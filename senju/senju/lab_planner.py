"""Deterministic coverage-gap planning for Senju local/owned labs.

This is the PR #252 self-development contract.  It turns bounded evidence into
content-addressed *local* lab manifests only; it does not choose public targets,
create exploit payloads, or widen network authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from .targets.base import ARCHETYPES, VULN_CLASSES

MANIFEST_SCHEMA = "senju-auto-lab/v3"
COVERAGE_THRESHOLD = 8
MAX_HIT_COUNT = 1_000_000
MAX_MANIFESTS = 32
MAX_SURFACES_PER_MANIFEST = 15
LAB_ARCHETYPES = tuple(sorted(ARCHETYPES))


def _bounded_nonnegative_int(value: Any, *, maximum: int = MAX_HIT_COUNT) -> int:
    """Normalize untrusted persisted counters without letting bool/NaN leak in."""
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(maximum, number))


def analyze_coverage(evolution_summary: dict[str, Any]) -> dict[str, int]:
    if not isinstance(evolution_summary, dict):
        raise ValueError("evolution summary must be a JSON object")
    counts = {vc: 0 for vc in VULN_CLASSES}
    raw = evolution_summary.get("vuln_class_hits", {})
    if raw is None:
        return counts
    if not isinstance(raw, dict):
        raise ValueError("vuln_class_hits must be an object")
    for vc in VULN_CLASSES:
        counts[vc] = _bounded_nonnegative_int(raw.get(vc, 0))
    return counts


def find_gaps(coverage: dict[str, int]) -> list[str]:
    """Stable gap order: lowest coverage first, then canonical class name."""
    gaps = [vc for vc in VULN_CLASSES if _bounded_nonnegative_int(coverage.get(vc, 0)) < COVERAGE_THRESHOLD]
    return sorted(gaps, key=lambda vc: (_bounded_nonnegative_int(coverage.get(vc, 0)), vc))


def _elo_loss_weight(evolution_summary: dict[str, Any], vc: str) -> float:
    raw = evolution_summary.get("vuln_class_elo", {})
    if not isinstance(raw, dict):
        return 1.0
    entry = raw.get(vc)
    if not isinstance(entry, dict):
        return 1.0
    wins = _bounded_nonnegative_int(entry.get("wins", 0))
    losses = _bounded_nonnegative_int(entry.get("losses", 0))
    total = wins + losses
    return 1.0 if total <= 0 else 1.0 + (losses / total) * 2.0


def _priority_order(summary: dict[str, Any], coverage: dict[str, int]) -> list[str]:
    """Coverage remains primary; ELO loss breaks ties toward weak classes."""
    gaps = find_gaps(coverage)
    return sorted(
        gaps,
        key=lambda vc: (
            _bounded_nonnegative_int(coverage.get(vc, 0)),
            -_elo_loss_weight(summary, vc),
            vc,
        ),
    )


def _existing_covered_classes(output_dir: Path) -> set[str]:
    covered: set[str] = set()
    if not output_dir.exists():
        return covered
    for path in sorted(output_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
            continue
        gaps = payload.get("coverage_gaps", [])
        if isinstance(gaps, list):
            covered.update(str(vc) for vc in gaps if vc in VULN_CLASSES)
    return covered


def _canonical_without_fingerprint(payload: dict[str, Any]) -> bytes:
    value = {k: v for k, v in payload.items() if k != "fingerprint"}
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _with_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["fingerprint"] = hashlib.sha256(_canonical_without_fingerprint(result)).hexdigest()
    return result


def generate_manifest(name: str, archetype: str, gap_vulns: list[str], seed: int = 42) -> dict[str, Any]:
    if not gap_vulns:
        raise ValueError("gap_vulns cannot be empty")
    rng = random.Random(int(seed))
    surfaces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for vc in gap_vulns[:MAX_SURFACES_PER_MANIFEST]:
        if vc not in VULN_CLASSES or vc in seen:
            continue
        seen.add(vc)
        surfaces.append(
            {
                "name": f"{name}:{vc.replace('_', '-')}",
                "vuln_class": vc,
                "difficulty": round(rng.uniform(0.3, 0.9), 3),
            }
        )
    payload = {
        "schema": MANIFEST_SCHEMA,
        "name": name,
        "archetype": archetype,
        "host": None,
        "description": "Auto-generated local lab from bounded coverage/ELO evidence",
        "coverage_gaps": [item["vuln_class"] for item in surfaces],
        "surfaces": surfaces,
    }
    return _with_fingerprint(payload)


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("evolution summary exceeds 2 MiB")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid evolution summary JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("evolution summary must be a JSON object")
    return payload


def plan(
    evolution_summary_path: str | Path,
    output_dir: str | Path,
    max_manifests: int = 10,
) -> list[Path]:
    if isinstance(max_manifests, bool) or not 1 <= int(max_manifests) <= MAX_MANIFESTS:
        raise ValueError(f"max_manifests must be between 1 and {MAX_MANIFESTS}")

    summary = _load_summary(Path(evolution_summary_path))
    coverage = analyze_coverage(summary)
    ordered = _priority_order(summary, coverage)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    already = _existing_covered_classes(out_dir)
    gaps = [vc for vc in ordered if vc not in already]
    if not gaps:
        return []

    count = min(int(max_manifests), len(gaps))
    chunk_size = max(1, math.ceil(len(gaps) / count))
    raw_seed = summary.get("seed", 42)
    seed = _bounded_nonnegative_int(raw_seed, maximum=2_147_483_647) or 42

    written: list[Path] = []
    for index in range(count):
        chunk = gaps[index * chunk_size : (index + 1) * chunk_size]
        if not chunk:
            break
        archetype = LAB_ARCHETYPES[index % len(LAB_ARCHETYPES)]
        identity = hashlib.sha256(
            json.dumps(
                {"archetype": archetype, "coverage_gaps": chunk, "seed": seed + index},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:12]
        name = f"auto-lab-{archetype.replace('_', '-')}-{identity}"
        path = out_dir / f"{name}.json"
        manifest = generate_manifest(name, archetype, chunk, seed + index)
        encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") == encoded:
            continue
        path.write_text(encoded, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="senju/state/last-evolution-summary.json")
    parser.add_argument("--out", default="senju/labs")
    parser.add_argument("--max", type=int, default=10)
    args = parser.parse_args()
    for generated in plan(args.summary, args.out, args.max):
        print(f"Generated: {generated}")
