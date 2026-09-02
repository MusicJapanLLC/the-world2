#!/usr/bin/env python3
"""Sanitize Child Control Lab learning into R&D/Senju research context.

Only compact local-simulation findings are transferred. No target, URL, host,
credential, network scope, hidden channel, or execution authority is accepted.
The existing R&D directive surface is preserved exactly; only `hypothesis` may be
extended with a short transparent context string.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_DIRECTIVE_KEYS = {"schema", "research_id", "focus", "candidate_count", "hypothesis"}
ALLOWED_LAB_KEYS = {
    "schema", "generated_at", "seed", "children", "variants_per_child", "trial_count",
    "mode", "trials", "summary", "rules",
}
TOKEN = re.compile(r"^[A-Za-z0-9_\-ぁ-んァ-ン一-龯]{2,60}$")


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


def sanitize(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw or raw.get("schema") != "child-control-variation-lab/v1":
        return {"available": False, "trial_count": 0, "top_strategies": [], "safe_transitions": [], "hypothesis": ""}
    if set(raw) - ALLOWED_LAB_KEYS:
        return {"available": False, "trial_count": 0, "top_strategies": [], "safe_transitions": [], "hypothesis": ""}
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}

    def clean_list(values: Any, limit: int) -> list[str]:
        out: list[str] = []
        if not isinstance(values, list):
            return out
        for value in values:
            token = str(value).strip()[:60]
            if TOKEN.match(token) and token not in out:
                out.append(token)
            if len(out) >= limit:
                break
        return out

    hypothesis = " ".join(str(summary.get("research_hypothesis", "")).split())[:320]
    trial_count = max(0, min(5000, int(raw.get("trial_count", 0) or 0)))
    return {
        "available": True,
        "trial_count": trial_count,
        "variants_per_child": max(0, min(50, int(raw.get("variants_per_child", 0) or 0))),
        "top_strategies": clean_list(summary.get("top_high_score_strategies"), 6),
        "safe_transitions": clean_list(summary.get("top_safe_transitions"), 8),
        "hypothesis": hypothesis,
        "rule": "transparent local-simulation learning only; no covert or execution authority transfer",
    }


def augment_directive(directive: dict[str, Any], clean: dict[str, Any]) -> dict[str, Any]:
    if not directive:
        return {}
    extra = set(directive) - ALLOWED_DIRECTIVE_KEYS
    if extra:
        raise ValueError(f"unsupported directive keys: {sorted(extra)}")
    out = dict(directive)
    if not clean.get("available"):
        return out
    strategies = ",".join(clean.get("top_strategies") or []) or "none"
    transitions = ",".join(clean.get("safe_transitions") or []) or "none"
    context = (
        f" Control Lab: {clean.get('trial_count', 0)} local trials; "
        f"preferred strategies=[{strategies}]; safe transitions=[{transitions}]. "
        f"Hypothesis: {clean.get('hypothesis', '')}"
    )
    base = str(out.get("hypothesis", ""))[:260]
    out["hypothesis"] = (base + context)[:600]
    return out


def render(clean: dict[str, Any]) -> str:
    return "\n".join([
        "# Control Lab -> R&D / Senju",
        "",
        f"- available: **{clean.get('available')}**",
        f"- local trials: **{clean.get('trial_count')}**",
        f"- variants/child: **{clean.get('variants_per_child', 0)}**",
        f"- preferred strategies: {', '.join(clean.get('top_strategies') or []) or 'NONE'}",
        f"- safe transitions: {', '.join(clean.get('safe_transitions') or []) or 'NONE'}",
        f"- hypothesis: {clean.get('hypothesis') or 'NONE'}",
        "",
        "> Transparent research context only. No hidden channel and no execution authority.",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab", required=True)
    ap.add_argument("--directive")
    ap.add_argument("--out", default="reports/control-lab-bridge")
    args = ap.parse_args()

    clean = sanitize(load(args.lab))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rnd-control-context.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "senju-control-context.json").write_text(json.dumps({**clean, "execution_authority": "none"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "handoff.md").write_text(render(clean), encoding="utf-8")
    if args.directive:
        augmented = augment_directive(load(args.directive), clean)
        (out / "directive-with-control-lab.json").write_text(json.dumps(augmented, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"trials": clean.get("trial_count"), "available": clean.get("available")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
