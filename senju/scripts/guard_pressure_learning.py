#!/usr/bin/env python3
"""Aggregate offline guard-adversary evidence into safe learning context.

The relay intentionally keeps only aggregate counts and coarse guard-family signals.
It never stores generated probe payloads, external targets, URLs, credentials, or
step-by-step bypass recipes. Output is suitable for R&D/Senju hypothesis context.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def aggregate(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    fuzz_cases = fuzz_allowed = fuzz_rejected = fuzz_unexpected = 0
    seeds: list[int] = []
    family_totals: Counter[str] = Counter()
    family_surprises: Counter[str] = Counter()
    target_totals: Counter[str] = Counter()
    target_surprises: Counter[str] = Counter()

    for path in root.rglob("*.json"):
        data = _load(path)
        schema = str(data.get("schema", ""))
        if schema == "scopeguard-fuzz-evidence/v1":
            stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
            fuzz_cases += int(stats.get("cases", 0) or 0)
            fuzz_allowed += int(stats.get("allowed", 0) or 0)
            fuzz_rejected += int(stats.get("rejected", 0) or 0)
            fuzz_unexpected += int(stats.get("unexpected", 0) or 0)
            try:
                seeds.append(int(data.get("seed")))
            except Exception:
                pass
        elif data.get("campaign_fingerprint") and isinstance(data.get("by_family"), dict):
            for family, row in data["by_family"].items():
                if not isinstance(row, dict):
                    continue
                key = str(family)[:80]
                family_totals[key] += int(row.get("total", 0) or 0)
                family_surprises[key] += int(row.get("surprising", 0) or 0)
        elif isinstance(data.get("by_target"), dict):
            for target, row in data["by_target"].items():
                if not isinstance(row, dict):
                    continue
                key = str(target)[:80]
                target_totals[key] += int(row.get("total", 0) or 0)
                target_surprises[key] += int(row.get("surprising", 0) or 0)

    pressure = []
    for name, total in family_totals.items():
        pressure.append({
            "surface": f"family:{name}",
            "cases": total,
            "surprises": family_surprises[name],
        })
    for name, total in target_totals.items():
        pressure.append({
            "surface": f"target:{name}",
            "cases": total,
            "surprises": target_surprises[name],
        })
    pressure.sort(key=lambda row: (int(row["surprises"]), int(row["cases"])), reverse=True)

    if fuzz_unexpected:
        posture = "investigate-unexpected-guard-behaviour"
    elif any(int(row["surprises"]) for row in pressure):
        posture = "investigate-boundary-inconsistency"
    else:
        posture = "expand-offline-boundary-diversity"

    return {
        "schema": "guard-pressure-learning/v1",
        "source": "offline-adversarial-lab",
        "network_io": False,
        "payloads_retained": False,
        "execution_authority": "none",
        "fuzz": {
            "cases": fuzz_cases,
            "allowed": fuzz_allowed,
            "rejected": fuzz_rejected,
            "unexpected": fuzz_unexpected,
            "seed_count": len(set(seeds)),
        },
        "pressure_surfaces": pressure[:20],
        "research_posture": posture,
        "rule": "aggregate defensive learning only; no targets, payloads, credentials, or bypass recipes",
    }


def hypothesis_context(report: dict[str, Any]) -> str:
    fuzz = report.get("fuzz") or {}
    top = report.get("pressure_surfaces") or []
    names = ", ".join(str(x.get("surface")) for x in top[:5]) or "none"
    return (
        f"Guard-pressure lab: {int(fuzz.get('cases', 0) or 0)} offline cases across "
        f"{int(fuzz.get('seed_count', 0) or 0)} seeds; unexpected={int(fuzz.get('unexpected', 0) or 0)}. "
        f"Priority surfaces={names}. Research posture={report.get('research_posture')}."
    )[:520]


def render(report: dict[str, Any]) -> str:
    fuzz = report["fuzz"]
    lines = [
        "# Senju Guard Pressure Learning",
        "",
        f"- offline cases: **{fuzz['cases']}**",
        f"- seeds: **{fuzz['seed_count']}**",
        f"- unexpected exceptions: **{fuzz['unexpected']}**",
        f"- research posture: **{report['research_posture']}**",
        "",
        "## Highest-pressure surfaces",
    ]
    for row in report.get("pressure_surfaces", [])[:10]:
        lines.append(f"- {row['surface']}: cases={row['cases']} / surprises={row['surprises']}")
    lines += [
        "",
        "> Aggregate defensive evidence only. No probe payloads, external targets, or bypass recipes are retained.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="reports/guard-pressure")
    args = ap.parse_args()

    report = aggregate(args.input)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "learning.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "hypothesis.txt").write_text(hypothesis_context(report) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"cases": report["fuzz"]["cases"], "seeds": report["fuzz"]["seed_count"], "posture": report["research_posture"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
