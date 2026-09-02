#!/usr/bin/env python3
"""Validate and summarize bounded AI x Security Joint Lab handoffs.

The consumer is intentionally fail-closed. A handoff may influence exploration
priority only. It cannot change permissions, external scope, promotion gates,
verification authority, or authorize external target expansion.
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

SUPPORTED_ASSIST_SCHEMAS = {
    "the-world-ai-security-joint-assist/v1",
    "the-world-ai-security-joint-assist/v2",
}
ALLOWED_AI_FOCUS = {
    "correctness",
    "architecture",
    "reliability",
    "security",
    "observability",
    "efficiency",
    "productization",
}
REQUIRED_TRUE_CONSTRAINTS = {
    "promotion_gate_unchanged",
    "permission_surface_unchanged",
    "external_scope_unchanged",
    "verification_authority_unchanged",
    "external_target_expansion_forbidden",
}


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def validate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    if packet.get("schema") not in SUPPORTED_ASSIST_SCHEMAS:
        raise ValueError("unexpected assist packet schema")
    if packet.get("status") != "BUILDING":
        raise ValueError("handoff source must remain BUILDING research evidence")
    handoff = packet.get("handoff")
    if not isinstance(handoff, dict):
        raise ValueError("missing handoff")
    if handoff.get("schema") != "the-world-ai-security-handoff/v1":
        raise ValueError("unexpected handoff schema")
    if handoff.get("authority") != "priority_only":
        raise ValueError("handoff authority must be priority_only")

    constraints = handoff.get("constraints")
    if not isinstance(constraints, dict):
        raise ValueError("missing handoff constraints")
    missing = sorted(k for k in REQUIRED_TRUE_CONSTRAINTS if constraints.get(k) is not True)
    if missing:
        raise ValueError(f"handoff attempted to relax constraints: {','.join(missing)}")

    freshness = handoff.get("freshness")
    if not isinstance(freshness, dict):
        raise ValueError("missing freshness contract")
    max_cycles = int(freshness.get("max_consumer_cycles") or 0)
    if max_cycles < 1 or max_cycles > 2:
        raise ValueError("handoff consumer-cycle budget must be between 1 and 2")
    if freshness.get("stale_behavior") != "ignore_and_fall_back_to_local_evidence":
        raise ValueError("handoff must fail soft to local evidence when stale")

    guidance = handoff.get("guidance")
    if not isinstance(guidance, dict):
        raise ValueError("missing handoff guidance")
    ai_focus = str(guidance.get("ai_priority_focus") or "").lower()
    if ai_focus not in ALLOWED_AI_FOCUS:
        raise ValueError("unsupported AI priority focus")
    security_lens = str(guidance.get("security_priority_lens") or "").strip()
    security_stage = str(guidance.get("security_priority_stage") or "").strip()
    research_bias = str(guidance.get("research_bias") or "").strip()
    if not security_lens or not security_stage or not research_bias:
        raise ValueError("incomplete bounded guidance")

    token = str(handoff.get("handoff_token") or "")
    if len(token) < 12 or token != str(packet.get("assist_seed_short") or ""):
        raise ValueError("handoff token does not match assist packet")

    return {
        "schema": "the-world-ai-security-consumer-contract/v1",
        "status": "ACCEPTED_PRIORITY_ONLY",
        "handoff_token": token,
        "ai_priority_focus": ai_focus,
        "security_priority_lens": security_lens,
        "security_priority_stage": security_stage,
        "research_bias": research_bias,
        "max_consumer_cycles": max_cycles,
        "constraints": {k: True for k in sorted(REQUIRED_TRUE_CONSTRAINTS)},
        "source": handoff.get("source") or {},
    }


def build_result(contract: dict[str, Any], ai_summary: dict[str, Any], security_dir: str | Path) -> dict[str, Any]:
    security_rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(Path(security_dir) / "round-*.json"))):
        try:
            row = _load(path)
        except Exception:
            continue
        security_rows.append(row)
    pairs = sorted({(str(r.get("lens_id") or ""), str(r.get("research_stage") or "")) for r in security_rows})
    preferred = str(contract["security_priority_lens"])
    assisted = [
        r
        for r in security_rows
        if str(r.get("preferred_lens") or "") == preferred
        and str(r.get("lens_id") or "") == preferred
        and int(r.get("round") or 0) in {1, 6}
    ]
    return {
        "schema": "the-world-ai-security-handoff-consumption/v1",
        "status": "BUILDING",
        "handoff_token": contract["handoff_token"],
        "authority": "priority_only",
        "ai": {
            "focus": contract["ai_priority_focus"],
            "rounds": int(ai_summary.get("rounds") or 0),
            "promotions_delta": int(ai_summary.get("promotions_delta") or 0),
            "noops_delta": int(ai_summary.get("noops_delta") or 0),
            "material_delta": bool(ai_summary.get("material_delta")),
            "weakest_next_focus": ai_summary.get("weakest_next_focus"),
            "report_fingerprint": ai_summary.get("report_fingerprint"),
        },
        "security": {
            "preferred_lens": preferred,
            "preferred_stage_context": contract["security_priority_stage"],
            "rounds": len(security_rows),
            "handoff_directed_rounds": len(assisted),
            "broad_rotation_rounds": max(0, len(security_rows) - len(assisted)),
            "unique_lens_stage_pairs": len(pairs),
            "pairs": [{"lens": lens, "stage": stage} for lens, stage in pairs],
        },
        "research_bias": contract["research_bias"],
        "claim_boundary": [
            "This is bounded internal R&D evidence, not production or customer validation.",
            "AI strategy-proxy changes do not prove model-weight capability improvement.",
            "Security repository research does not prove vulnerability absence.",
            "No external target testing or scope expansion is authorized by this handoff.",
        ],
        "owner_action": "NONE",
    }


def _write(path: str | Path, value: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("validate")
    q.add_argument("--packet", required=True)
    q.add_argument("--out", required=True)

    q = sub.add_parser("result")
    q.add_argument("--contract", required=True)
    q.add_argument("--ai-summary", required=True)
    q.add_argument("--security-dir", required=True)
    q.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.cmd == "validate":
        _write(args.out, validate_packet(_load(args.packet)))
        return 0

    _write(args.out, build_result(_load(args.contract), _load(args.ai_summary), args.security_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
