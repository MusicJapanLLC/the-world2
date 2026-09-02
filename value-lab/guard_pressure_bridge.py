#!/usr/bin/env python3
"""Sanitize guard-pressure learning and fold it into an existing R&D directive.

Only the existing hypothesis string may change. This bridge does not add execution
keys, targets, URLs, network authority, permissions, credentials, or write authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ALLOWED_DIRECTIVE_KEYS = {"schema", "research_id", "focus", "candidate_count", "hypothesis"}


def load(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sanitize(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != "guard-pressure-learning/v1":
        return {"available": False, "cases": 0, "seed_count": 0, "unexpected": 0, "surfaces": [], "posture": "none"}
    fuzz = raw.get("fuzz") if isinstance(raw.get("fuzz"), dict) else {}
    surfaces = []
    for row in raw.get("pressure_surfaces") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("surface", ""))[:80]
        if not name or any(x in name.lower() for x in ("http://", "https://", "@", "secret", "credential")):
            continue
        surfaces.append({
            "surface": name,
            "cases": max(0, min(50_000_000, int(row.get("cases", 0) or 0))),
            "surprises": max(0, min(50_000_000, int(row.get("surprises", 0) or 0))),
        })
        if len(surfaces) >= 8:
            break
    return {
        "available": True,
        "cases": max(0, min(100_000_000, int(fuzz.get("cases", 0) or 0))),
        "seed_count": max(0, min(100, int(fuzz.get("seed_count", 0) or 0))),
        "unexpected": max(0, min(1_000_000, int(fuzz.get("unexpected", 0) or 0))),
        "surfaces": surfaces,
        "posture": str(raw.get("research_posture", "expand-offline-boundary-diversity"))[:100],
        "execution_authority": "none",
    }


def augment(directive: dict[str, Any], clean: dict[str, Any]) -> dict[str, Any]:
    extra = set(directive) - ALLOWED_DIRECTIVE_KEYS
    if extra:
        raise ValueError(f"unsupported directive keys: {sorted(extra)}")
    out = dict(directive)
    if not clean.get("available"):
        return out
    surfaces = ", ".join(row["surface"] for row in clean.get("surfaces", [])[:4]) or "none"
    context = (
        f" Guard-pressure context: {clean.get('cases', 0)} offline cases / "
        f"{clean.get('seed_count', 0)} seeds / unexpected={clean.get('unexpected', 0)}; "
        f"pressure={surfaces}; posture={clean.get('posture')}."
    )
    out["hypothesis"] = (str(out.get("hypothesis", ""))[:320] + context)[:600]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--learning", required=True)
    ap.add_argument("--directive", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    clean = sanitize(load(args.learning))
    result = augment(load(args.directive), clean)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"available": clean["available"], "cases": clean["cases"], "seed_count": clean["seed_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
