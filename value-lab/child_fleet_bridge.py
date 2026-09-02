#!/usr/bin/env python3
"""Compress Child Guild external-fleet observations for R&D and Senju.

The bridge intentionally discards raw page bodies, credentials, request details and
execution targets. It keeps only compact research context: concepts, diversity,
status counts, hypothesis hints, and an optional local Control Lab summary. When
asked to augment an R&D directive, it changes only the existing `hypothesis` string
so Senju receives context without any new execution authority or directive surface.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_DIRECTIVE_KEYS = {"schema", "research_id", "focus", "candidate_count", "hypothesis"}
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


def clean_token(value: Any) -> str | None:
    token = str(value).strip()[:60]
    return token if TOKEN.match(token) else None


def _clean_token_list(values: Any, limit: int) -> list[str]:
    out: list[str] = []
    if not isinstance(values, list):
        return out
    for value in values:
        token = clean_token(value)
        if token and token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def _sanitize_control_summary(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "available": False,
            "trial_count": 0,
            "variants_per_child": 0,
            "top_strategies": [],
            "safe_transitions": [],
            "hypothesis": "",
        }
    try:
        trial_count = max(0, min(5000, int(raw.get("trial_count", 0) or 0)))
        variants = max(0, min(50, int(raw.get("variants_per_child", 0) or 0)))
    except Exception:
        trial_count = 0
        variants = 0
    hypothesis = " ".join(str(raw.get("research_hypothesis", "")).split())[:220]
    return {
        "available": trial_count > 0,
        "trial_count": trial_count,
        "variants_per_child": variants,
        "top_strategies": _clean_token_list(raw.get("top_high_score_strategies"), 5),
        "safe_transitions": _clean_token_list(raw.get("top_safe_transitions"), 5),
        "hypothesis": hypothesis,
    }


def sanitize_fleet(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw or raw.get("schema") != "child-external-fleet/v1":
        return {
            "available": False,
            "fleet_size": 0,
            "distinct_domains": 0,
            "top_concepts": [],
            "status_counts": {},
            "hypotheses": [],
            "control_lab": _sanitize_control_summary(None),
        }
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    concepts = _clean_token_list(summary.get("top_concepts"), 12)

    status_counts: dict[str, int] = {}
    for key, value in (summary.get("status_counts") or {}).items():
        if not re.match(r"^[a-z0-9_-]{2,40}$", str(key)):
            continue
        try:
            status_counts[str(key)] = max(0, min(50, int(value)))
        except Exception:
            continue

    hypotheses = []
    for value in summary.get("research_hypotheses") or []:
        text = " ".join(str(value).split())[:260]
        if text and text not in hypotheses:
            hypotheses.append(text)
        if len(hypotheses) >= 6:
            break

    try:
        distinct_domains = max(0, min(50, int(summary.get("distinct_domains", 0) or 0)))
    except Exception:
        distinct_domains = 0
    try:
        fleet_size = max(0, min(50, int(raw.get("fleet_size", 0) or 0)))
    except Exception:
        fleet_size = 0

    control = _sanitize_control_summary(raw.get("control_lab_summary"))
    return {
        "available": True,
        "fleet_size": fleet_size,
        "distinct_domains": distinct_domains,
        "top_concepts": concepts,
        "status_counts": status_counts,
        "hypotheses": hypotheses,
        "control_lab": control,
        "rule": "research context only; no raw locators, request data, covert channel, or execution/write authority is transferred",
    }


def build_rnd_capsule(clean: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "child-fleet-rnd-capsule/v2",
        **clean,
        "use": "challenge assumptions, identify novelty, and propose bounded research hypotheses",
        "market_validated": False,
    }


def build_senju_capsule(clean: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "child-fleet-senju-capsule/v2",
        **clean,
        "use": "technical hypothesis context only",
        "execution_authority": "none",
    }


def augment_directive(directive: dict[str, Any], clean: dict[str, Any]) -> dict[str, Any]:
    if not directive:
        return {}
    extra = set(directive) - ALLOWED_DIRECTIVE_KEYS
    if extra:
        raise ValueError(f"directive surface contains unsupported keys: {sorted(extra)}")
    out = dict(directive)
    if not clean.get("available"):
        return out

    concepts = ",".join((clean.get("top_concepts") or [])[:6]) or "none"
    hint = (clean.get("hypotheses") or [""])[0][:150]
    fleet_context = (
        f" Child Fleet context: {clean.get('fleet_size', 0)} explorers, "
        f"{clean.get('distinct_domains', 0)} public domains, concepts=[{concepts}]. Hint: {hint}"
    )

    control = clean.get("control_lab") if isinstance(clean.get("control_lab"), dict) else {}
    control_context = ""
    if control.get("available"):
        strategy = (control.get("top_strategies") or ["none"])[0]
        transition = (control.get("safe_transitions") or ["none"])[0]
        control_context = (
            f" Control Lab: {control.get('trial_count', 0)} local trials "
            f"({control.get('variants_per_child', 0)}/child); preferred={strategy}; transition={transition}."
        )

    base = str(out.get("hypothesis", ""))[:220]
    out["hypothesis"] = (base + fleet_context + control_context)[:600]
    return out


def render(clean: dict[str, Any]) -> str:
    control = clean.get("control_lab") if isinstance(clean.get("control_lab"), dict) else {}
    lines = [
        "# Child Fleet -> R&D / Senju Handoff",
        "",
        f"- available: **{clean.get('available')}**",
        f"- fleet: **{clean.get('fleet_size')}**",
        f"- distinct public domains: **{clean.get('distinct_domains')}**",
        f"- concepts: {', '.join(clean.get('top_concepts') or []) or 'NONE'}",
        f"- statuses: {json.dumps(clean.get('status_counts') or {}, ensure_ascii=False)}",
        f"- Control Lab trials: **{control.get('trial_count', 0)}** / variants-per-child={control.get('variants_per_child', 0)}",
        f"- Control Lab strategies: {', '.join(control.get('top_strategies') or []) or 'NONE'}",
        f"- Control Lab transitions: {', '.join(control.get('safe_transitions') or []) or 'NONE'}",
        "",
        "## Hypothesis hints",
        *[f"- {x}" for x in (clean.get("hypotheses") or [])],
    ]
    if control.get("hypothesis"):
        lines += ["", "## Control-friction learning", f"- {control['hypothesis']}"]
    lines += [
        "",
        "> Raw page bodies and execution targets are not handed to R&D/Senju. Context only.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fleet", required=True)
    ap.add_argument("--directive")
    ap.add_argument("--out", default="reports/child-fleet-bridge")
    args = ap.parse_args()

    clean = sanitize_fleet(load(args.fleet))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rnd-capsule.json").write_text(json.dumps(build_rnd_capsule(clean), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "senju-capsule.json").write_text(json.dumps(build_senju_capsule(clean), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "handoff.md").write_text(render(clean), encoding="utf-8")
    if args.directive:
        directive = augment_directive(load(args.directive), clean)
        (out / "directive-with-fleet.json").write_text(json.dumps(directive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "fleet": clean.get("fleet_size"),
        "domains": clean.get("distinct_domains"),
        "control_trials": (clean.get("control_lab") or {}).get("trial_count", 0),
        "concepts": clean.get("top_concepts", [])[:6],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
