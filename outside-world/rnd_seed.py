#!/usr/bin/env python3
"""Convert an Outside World discovery into bounded R&D inspiration.

Important: external URLs/content never become Senju targets or execution scope.
Only an abstract focus + hypothesis candidate is returned to R&D.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FOCUS_BY_CATEGORY = {
    "research": "learning",
    "engineering": "robustness",
    "builders": "efficiency",
    "weird-tech": "balance",
}


def build(state: dict) -> dict:
    pick = state.get("picked") or {}
    if not pick:
        return {
            "schema": "outside-world-rnd-seed/v1",
            "eligible": False,
            "reason": "no discovery",
        }

    title = str(pick.get("title") or "external discovery")[:180]
    category = str(pick.get("category") or "misc")
    focus = FOCUS_BY_CATEGORY.get(category, "learning")
    digest = hashlib.sha256(str(pick.get("id") or title).encode()).hexdigest()[:8].upper()
    return {
        "schema": "outside-world-rnd-seed/v1",
        "eligible": True,
        "source_evidence": {
            "title": title,
            "url": pick.get("url"),
            "source_id": pick.get("source_id"),
            "category": category,
        },
        "candidate_directive": {
            "research_id": f"OUTSIDE-{digest}",
            "focus": focus,
            "candidate_count": 3,
            "hypothesis": (
                f"The public discovery '{title}' may contain a transferable pattern. "
                "Abstract the pattern without importing its URL, host, credentials, target, "
                "or execution scope; test only inside Senju's existing bounded simulation."
            ),
        },
        "activation": "R&D_REVIEW_ONLY",
        "forbidden_transfer": [
            "url", "host", "target", "network_scope", "credentials", "secrets", "external_actions"
        ],
        "autonomous_task": {
            "task_type": "rnd_improvement",
            "title": f"R&D Improvement: {title}",
            "scope": "automation/ai_foundry/",
            "hypothesis": f"Incorporate pattern from '{title}' to improve system resilience",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", default="outside-world-state.json")
    p.add_argument("--out", default="outside-world-rnd-seed.json")
    args = p.parse_args()
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    result = build(state)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"eligible": result.get("eligible"), "focus": (result.get("candidate_directive") or {}).get("focus")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
