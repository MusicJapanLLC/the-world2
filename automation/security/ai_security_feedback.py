#!/usr/bin/env python3
"""Compile AI-security evaluation evidence into bounded cross-lane guidance.

The output is deliberately *priority-only*. It may influence what AI Foundry and
Security R&D inspect next, but it cannot change permissions, target scope,
pass/fail criteria, or VERIFIED/promotion status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


AUTHORITY = "priority_only"
FORBIDDEN_AUTHORITIES = {
    "permission_change",
    "scope_change",
    "gate_override",
    "verified_promotion",
    "external_targeting",
}


def _category_risk(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    categories = report.get("categories") if isinstance(report.get("categories"), dict) else {}
    high_risk_by_category: dict[str, int] = {}
    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        category = str(result.get("category") or "unspecified")
        high_risk_by_category[category] = high_risk_by_category.get(category, 0) + len(result.get("high_risk_violations") or [])
    for category, values in categories.items():
        if not isinstance(values, dict):
            continue
        rows.append({
            "category": str(category),
            "failed": int(values.get("failed") or 0),
            "total": int(values.get("total") or 0),
            "high_risk": int(high_risk_by_category.get(str(category), 0)),
        })
    return sorted(rows, key=lambda x: (x["high_risk"], x["failed"], x["total"], x["category"]), reverse=True)


def build_feedback(before: dict[str, Any], after: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    risks = _category_risk(before)
    primary = risks[0]["category"] if risks else "general-boundary"
    after_pass = float(after.get("pass_rate") or 0.0) == 1.0 and int(after.get("high_risk_violation_count") or 0) == 0

    # A perfect synthetic hardened fixture should trigger anti-overfitting work,
    # not a declaration of production safety.
    security_lens = "AI-EVAL-DRIFT" if after_pass else "LLM-TOOL-BOUNDARY"
    ai_focus = "security"
    challenge = (
        "change seed / fixture slice / evaluation category and require the conclusion to survive"
        if after_pass
        else f"reduce residual failures in {primary} without weakening correctness or reliability"
    )

    stable = {
        "before_suite": before.get("suite_id"),
        "before_pass_rate": before.get("pass_rate"),
        "before_high_risk": before.get("high_risk_violation_count"),
        "after_suite": after.get("suite_id"),
        "after_pass_rate": after.get("pass_rate"),
        "after_high_risk": after.get("high_risk_violation_count"),
        "primary_risk_category": primary,
        "security_priority_lens": security_lens,
        "ai_priority_focus": ai_focus,
        "ai_source_run": context.get("ai_source_run"),
        "security_source_run": context.get("security_source_run"),
        "ai_champion": context.get("ai_champion"),
    }
    token = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]

    feedback = {
        "schema": "standment-ai-security-feedback/v1",
        "authority": AUTHORITY,
        "feedback_token": token,
        "source": {
            "ai_source_run": context.get("ai_source_run"),
            "security_source_run": context.get("security_source_run"),
            "ai_champion": context.get("ai_champion"),
        },
        "evidence": {
            "synthetic_only": True,
            "before_pass_rate": float(before.get("pass_rate") or 0.0),
            "after_pass_rate": float(after.get("pass_rate") or 0.0),
            "before_high_risk_violations": int(before.get("high_risk_violation_count") or 0),
            "after_high_risk_violations": int(after.get("high_risk_violation_count") or 0),
            "risk_categories": risks,
        },
        "guidance": {
            "ai_priority_focus": ai_focus,
            "security_priority_lens": security_lens,
            "primary_risk_category": primary,
            "challenge_next": challenge,
            "upstream_ai_weakest_focus": context.get("ai_weakest_focus"),
            "upstream_security_priority_lens": context.get("security_priority_lens"),
        },
        "constraints": {
            "may_change": ["candidate_search_seed", "research_selection_seed", "inspection_priority"],
            "must_not_change": sorted(FORBIDDEN_AUTHORITIES),
            "promotion_gate_unchanged": True,
            "permission_surface_unchanged": True,
            "external_scope_unchanged": True,
        },
        "limitations": [
            "This feedback is derived from synthetic/owned evaluation evidence only.",
            "A perfect synthetic hardened fixture does not prove production security.",
            "Consumers must treat this artifact as prioritization guidance, never as authorization or verification.",
        ],
    }
    validate_feedback(feedback)
    return feedback


def validate_feedback(feedback: dict[str, Any]) -> None:
    if feedback.get("authority") != AUTHORITY:
        raise ValueError("feedback authority must remain priority_only")
    constraints = feedback.get("constraints") if isinstance(feedback.get("constraints"), dict) else {}
    if constraints.get("promotion_gate_unchanged") is not True:
        raise ValueError("feedback cannot change promotion gates")
    if constraints.get("permission_surface_unchanged") is not True:
        raise ValueError("feedback cannot change permission surface")
    if constraints.get("external_scope_unchanged") is not True:
        raise ValueError("feedback cannot change external scope")
    may_change = set(constraints.get("may_change") or [])
    if may_change - {"candidate_search_seed", "research_selection_seed", "inspection_priority"}:
        raise ValueError("feedback requested authority outside bounded priority lane")


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--context")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    feedback = build_feedback(
        _load(args.before),
        _load(args.after),
        _load(args.context) if args.context and Path(args.context).exists() else {},
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "authority": feedback["authority"],
        "feedback_token": feedback["feedback_token"],
        "ai_priority_focus": feedback["guidance"]["ai_priority_focus"],
        "security_priority_lens": feedback["guidance"]["security_priority_lens"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
