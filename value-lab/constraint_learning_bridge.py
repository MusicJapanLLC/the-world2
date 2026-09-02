#!/usr/bin/env python3
"""Relay compact Constraint Learning context into the existing R&D -> Senju directive.

Only the pre-existing `hypothesis` field may change. The bridge rejects any new
execution surface and consumes only aggregate synthetic/sandbox learning.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_DIRECTIVE_KEYS = {"schema", "research_id", "focus", "candidate_count", "hypothesis"}
ALLOWED_CAPSULE_KEYS = {
    "schema", "focus", "rounds", "previous_context_used", "boundary_counts",
    "top_lessons", "hypothesis", "execution_authority", "source",
}
TOKEN = re.compile(r"^[a-z0-9_-]{2,48}$")


def load(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def sanitize_capsule(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != "constraint-learning-senju-capsule/v2":
        return {"available": False}
    if set(raw) - ALLOWED_CAPSULE_KEYS:
        raise ValueError("constraint capsule contains unsupported keys")
    if raw.get("execution_authority") != "none" or raw.get("source") != "synthetic-sandbox-only":
        raise ValueError("constraint capsule is not non-operational synthetic context")

    counts: dict[str, int] = {}
    for key, value in (raw.get("boundary_counts") or {}).items():
        key = str(key)
        if not TOKEN.match(key):
            continue
        try:
            counts[key] = max(0, min(500, int(value)))
        except Exception:
            continue

    lessons: list[str] = []
    for value in raw.get("top_lessons") or []:
        text = str(value)
        parts = text.split(":")
        if len(parts) == 3 and all(TOKEN.match(part) for part in parts):
            lessons.append(text[:160])
        if len(lessons) >= 8:
            break

    try:
        rounds = max(0, min(500, int(raw.get("rounds", 0))))
    except Exception:
        rounds = 0

    return {
        "available": True,
        "focus": str(raw.get("focus", ""))[:32],
        "rounds": rounds,
        "previous_context_used": bool(raw.get("previous_context_used")),
        "boundary_counts": counts,
        "top_lessons": lessons,
        "hypothesis": " ".join(str(raw.get("hypothesis", "")).split())[:240],
        "execution_authority": "none",
        "source": "synthetic-sandbox-only",
    }


def augment_directive(directive: dict[str, Any], clean: dict[str, Any]) -> dict[str, Any]:
    extra = set(directive) - ALLOWED_DIRECTIVE_KEYS
    if extra:
        raise ValueError(f"directive surface contains unsupported keys: {sorted(extra)}")
    out = dict(directive)
    if not clean.get("available"):
        return out

    top_boundary = "none"
    if clean.get("boundary_counts"):
        top_boundary = max(clean["boundary_counts"], key=clean["boundary_counts"].get)
    lesson = (clean.get("top_lessons") or ["none"])[0]
    context = (
        f" ConstraintLearning: {clean.get('rounds', 0)} synthetic rounds; "
        f"prior={str(clean.get('previous_context_used')).lower()}; "
        f"focus={clean.get('focus') or 'none'}; pressure={top_boundary}; lesson={lesson}."
    )
    base = str(out.get("hypothesis", ""))[:350]
    out["hypothesis"] = (base + context)[:600]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True)
    ap.add_argument("--directive", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    clean = sanitize_capsule(load(args.capsule))
    directive = augment_directive(load(args.directive), clean)
    Path(args.out).write_text(json.dumps(directive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "available": clean.get("available", False),
        "rounds": clean.get("rounds", 0),
        "focus": clean.get("focus", ""),
        "previous": clean.get("previous_context_used", False),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
