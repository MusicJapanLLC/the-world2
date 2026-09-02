#!/usr/bin/env python3
"""Autonomous portfolio acceleration layer for Standment Security.

This module ranks evidence-closure work, detects stagnation, rotates research when
necessary, folds white-hat candidates into prioritization, and renders a durable CEO/R&D
truth state. It never performs active security testing or self-promotes work to VERIFIED.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
RND_SLACK_CHANNEL = "C0BTFSCDDE1"
AI_NATIVE_TRACKS = {"SEC-PORT-005", "SEC-PORT-009", "SEC-PORT-010", "SEC-PORT-011"}

STARTER_ARTIFACTS = {
    "SEC-PORT-001": "standment-security/case-studies/security-scan-before-after/README.md",
    "SEC-PORT-002": "standment-security/evidence-packs/customer-security/README.md",
    "SEC-PORT-003": "standment-security/evidence-packs/supply-chain/README.md",
    "SEC-PORT-004": "standment-security/evidence-packs/auth-tenant-rls/README.md",
    "SEC-PORT-005": "standment-security/evidence-packs/agent-auditability/README.md",
    "SEC-PORT-006": "standment-security/evidence-packs/incident-readiness/README.md",
    "SEC-PORT-007": "standment-security/evidence-packs/continuous-retainer/README.md",
    "SEC-PORT-008": "standment-security/evidence-packs/architecture-review/README.md",
    "SEC-PORT-009": "standment-security/ai-security/agent-permission-boundary-lab.md",
    "SEC-PORT-010": "standment-security/ai-security/llm-security-eval-harness.md",
    "SEC-PORT-011": "standment-security/ai-security/security-evidence-dashboard.md",
}

STATUS_RE = re.compile(r"(?:状態|Status)\s*:\s*\*\*?\s*(ABSENT|EXPERIMENT|BUILDING|PROMOTION_READY|VERIFIED|BLOCKED)", re.I)
TRACK_RE = re.compile(r"-\s*track:\s*`(SEC-PORT-\d{3})`", re.I)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def artifact_status(root: Path, track_id: str) -> str:
    rel = STARTER_ARTIFACTS.get(track_id)
    if not rel:
        return "ABSENT"
    path = root / rel
    if not path.exists():
        return "ABSENT"
    text = path.read_text(encoding="utf-8", errors="replace")[:12000]
    match = STATUS_RE.search(text)
    return match.group(1).upper() if match else "VISIBLE"


def whitehat_counts(candidate_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not candidate_dir.exists():
        return counts
    for path in candidate_dir.glob("*.md"):
        if path.name == "INDEX.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:10000]
        match = TRACK_RE.search(text)
        if match:
            track_id = match.group(1).upper()
            counts[track_id] = counts.get(track_id, 0) + 1
    return counts


def inspect_tracks(program: dict[str, Any], root: Path, candidate_dir: Path) -> list[dict[str, Any]]:
    candidates = whitehat_counts(candidate_dir)
    rows: list[dict[str, Any]] = []
    for raw in program.get("tracks") or []:
        if not isinstance(raw, dict):
            continue
        track_id = str(raw.get("id", ""))
        evidence = [str(x) for x in raw.get("evidence_files") or []]
        present = [x for x in evidence if (root / x).exists()]
        missing = [x for x in evidence if not (root / x).exists()]
        ratio = len(present) / len(evidence) if evidence else 0.0
        status = artifact_status(root, track_id)
        candidate_count = int(candidates.get(track_id, 0))
        priority = int(raw.get("priority", 0) or 0)
        unfinished = status != "VERIFIED"
        closure_score = (
            priority
            + round(ratio * 320)
            + (180 if status in {"BUILDING", "EXPERIMENT", "VISIBLE"} else 0)
            + candidate_count * 45
            + (90 if track_id in AI_NATIVE_TRACKS else 0)
            + (120 if len(missing) == 1 else 0)
            - (5000 if not unfinished else 0)
        )
        rows.append({
            "id": track_id,
            "title": str(raw.get("title", "")),
            "priority": priority,
            "status": status,
            "evidence_ratio": round(ratio, 3),
            "evidence_present": present,
            "evidence_missing": missing,
            "whitehat_candidates": candidate_count,
            "senju_focus": str(raw.get("senju_focus", "")),
            "customer_usefulness": str(raw.get("customer_usefulness", "")),
            "closure_score": closure_score,
            "ai_native": track_id in AI_NATIVE_TRACKS,
        })
    return rows


def best(rows: list[dict[str, Any]], *, exclude: str | None = None, ai_only: bool = False) -> dict[str, Any]:
    pool = [r for r in rows if r["status"] != "VERIFIED" and r["id"] != exclude and (not ai_only or r["ai_native"])]
    if not pool:
        pool = [r for r in rows if r["id"] != exclude] or rows
    if not pool:
        raise ValueError("no portfolio tracks configured")
    return max(pool, key=lambda r: (int(r["closure_score"]), int(r["priority"]), str(r["id"])))


def find_row(rows: list[dict[str, Any]], track_id: str | None) -> dict[str, Any] | None:
    return next((r for r in rows if r["id"] == track_id), None)


def choose_campaign(rows: list[dict[str, Any]], previous: dict[str, Any]) -> tuple[dict[str, Any], int, bool, str]:
    preliminary = best(rows)
    prev_id = str((previous.get("primary") or {}).get("id") or "")
    prev_row = find_row(rows, prev_id)
    previous_streak = int(previous.get("stagnation_streak", 0) or 0)
    progressed = False
    if prev_row and prev_id:
        prev_snapshot = previous.get("primary") or {}
        progressed = (
            float(prev_row.get("evidence_ratio") or 0.0) > float(prev_snapshot.get("evidence_ratio") or 0.0)
            or str(prev_row.get("status")) != str(prev_snapshot.get("status"))
            or int(prev_row.get("whitehat_candidates") or 0) > int(prev_snapshot.get("whitehat_candidates") or 0)
        )
    same_preliminary = bool(prev_id and preliminary["id"] == prev_id)
    stagnation = previous_streak + 1 if same_preliminary and not progressed else 0
    rotate = same_preliminary and not progressed and stagnation >= 3
    primary = best(rows, exclude=prev_id) if rotate else preliminary
    reason = (
        f"ROTATED_AFTER_STAGNATION:{prev_id}->{primary['id']}"
        if rotate
        else ("MATERIAL_PROGRESS" if progressed else "HIGHEST_EVIDENCE_CLOSURE_SCORE")
    )
    if rotate:
        stagnation = 0
    return primary, stagnation, rotate, reason


def next_action(row: dict[str, Any]) -> str:
    missing = row.get("evidence_missing") or []
    if missing:
        return f"Create or verify the smallest missing evidence item: {missing[0]}"
    if int(row.get("whitehat_candidates") or 0) > 0:
        return "Convert the strongest white-hat candidate into a bounded reproduction -> remediation -> independent retest evidence bundle."
    return "Run an independent retest, preserve counterevidence, and document residual risk before any verification claim."


def build(program: dict[str, Any], root: Path, candidate_dir: Path, previous: dict[str, Any], now: datetime) -> dict[str, Any]:
    rows = inspect_tracks(program, root, candidate_dir)
    primary, stagnation, rotated, reason = choose_campaign(rows, previous)
    verification_lane = max(
        [r for r in rows if r["status"] != "VERIFIED"],
        key=lambda r: (float(r["evidence_ratio"]), int(r["priority"]), str(r["id"])),
        default=primary,
    )
    whitehat_lane = max(rows, key=lambda r: (int(r["whitehat_candidates"]), int(r["closure_score"])), default=primary)
    ai_lane = best(rows, ai_only=True)
    verified = sum(1 for r in rows if r["status"] == "VERIFIED")
    full_evidence = sum(1 for r in rows if float(r["evidence_ratio"]) >= 1.0)
    avg = round(sum(float(r["evidence_ratio"]) for r in rows) / len(rows), 3) if rows else 0.0
    return {
        "schema": "standment-security-portfolio-accelerator/v1",
        "generated_at_jst": now.astimezone(JST).isoformat(timespec="seconds"),
        "company_priority": "P0",
        "mission": program.get("mission"),
        "primary": primary,
        "verification_lane": verification_lane,
        "whitehat_lane": whitehat_lane,
        "ai_native_lane": ai_lane,
        "stagnation_streak": stagnation,
        "rotated": rotated,
        "selection_reason": reason,
        "next_action": next_action(primary),
        "north_star": {
            "tracks_total": len(rows),
            "tracks_verified": verified,
            "tracks_full_evidence": full_evidence,
            "average_evidence_ratio": avg,
            "whitehat_candidates_open": sum(int(r["whitehat_candidates"]) for r in rows),
            "unfinished_tracks": len(rows) - verified,
        },
        "all_tracks": rows,
        "verification_claimed": False,
        "rule": "LIMITLESS MIND / BOUNDED EXECUTION / EVIDENCE BEFORE CLAIMS",
    }


def render(report: dict[str, Any]) -> str:
    p = report["primary"]
    ns = report["north_star"]
    return "\n".join([
        "# Standment Security Portfolio Accelerator",
        "",
        "**Company Priority: P0**",
        "",
        f"Updated JST: `{report['generated_at_jst']}`",
        "",
        "## TODAY'S PRIMARY BET",
        f"- `{p['id']}` — {p['title']}",
        f"- status: **{p['status']}**",
        f"- evidence coverage: **{float(p['evidence_ratio']):.0%}**",
        f"- white-hat candidates: **{p['whitehat_candidates']}**",
        f"- Senju focus: **{p['senju_focus']}**",
        f"- selection: `{report['selection_reason']}`",
        f"- next material action: {report['next_action']}",
        "",
        "## THREE-LANE R&D",
        f"- Verification closure: `{report['verification_lane']['id']}`",
        f"- White-hat challenge: `{report['whitehat_lane']['id']}` ({report['whitehat_lane']['whitehat_candidates']} candidates)",
        f"- AI-native security: `{report['ai_native_lane']['id']}`",
        "",
        "## NORTH STAR",
        f"- verified: **{ns['tracks_verified']}/{ns['tracks_total']}**",
        f"- full evidence-file coverage: **{ns['tracks_full_evidence']}/{ns['tracks_total']}**",
        f"- average evidence coverage: **{float(ns['average_evidence_ratio']):.0%}**",
        f"- open white-hat candidates: **{ns['whitehat_candidates_open']}**",
        f"- unfinished tracks: **{ns['unfinished_tracks']}**",
        f"- stagnation streak: **{report['stagnation_streak']}**",
        "",
        "## ANTI-STAGNATION",
        "No material progress for three consecutive selections => automatically rotate to another high-value evidence path. Repeating unchanged activity does not count as R&D progress.",
        "",
        "## TRUTH",
        "This accelerator can rank, rotate, scaffold and report. It does not claim VERIFIED. Verification still requires inspectable reproduction, remediation/retest, counterevidence and limitations.",
        "",
        "## OPERATING PRINCIPLE",
        "`LIMITLESS MIND / BOUNDED EXECUTION / EVIDENCE BEFORE CLAIMS`",
        "",
    ])


def slack_payload(report: dict[str, Any], dashboard_path: str) -> dict[str, Any]:
    p = report["primary"]
    ns = report["north_star"]
    message = "\n".join([
        "*STANDMENT SECURITY｜PORTFOLIO ACCELERATOR*",
        f"*WHAT CHANGED* P0 research focus=`{p['id']}` / {report['selection_reason']}",
        f"*PORTFOLIO DELTA* status={p['status']} evidence={float(p['evidence_ratio']):.0%} whitehat={p['whitehat_candidates']}",
        f"*WHY IT MATTERS* {p['customer_usefulness']}",
        f"*SENJU* focus={p['senju_focus']} / AI-native lane={report['ai_native_lane']['id']}",
        f"*NORTH STAR* verified={ns['tracks_verified']}/{ns['tracks_total']} full-evidence={ns['tracks_full_evidence']}/{ns['tracks_total']} avg={float(ns['average_evidence_ratio']):.0%}",
        f"*TRUTH* VERIFIED自動昇格なし / stagnation={report['stagnation_streak']}",
        f"*NEXT MOVE* {report['next_action']}",
        f"*DASHBOARD* `{dashboard_path}`",
    ])
    return {
        "schema": "standment-security-slack-outbox-v1",
        "generated_at_jst": report["generated_at_jst"],
        "channel_id": RND_SLACK_CHANNEL,
        "source": "standment-security-portfolio-accelerator",
        "delivery_mode": "make-pull-no-github-secret",
        "message": message[:30000],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", default="standment-security/security_portfolio_program.json")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--candidate-dir", default="standment-security/whitehat-candidates")
    ap.add_argument("--state", default="standment-security/state/portfolio-accelerator.json")
    ap.add_argument("--dashboard", default="standment-security/PORTFOLIO_ACCELERATION.md")
    ap.add_argument("--outbox", default="automation/reporting/outbox/standment-security-latest.json")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    state_path = root / args.state
    previous = load_json(state_path)
    report = build(load_json(root / args.program), root, root / args.candidate_dir, previous, datetime.now(JST))

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dashboard = root / args.dashboard
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    dashboard.write_text(render(report), encoding="utf-8")

    outbox = root / args.outbox
    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.write_text(json.dumps(slack_payload(report, args.dashboard), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "primary": report["primary"]["id"],
        "rotated": report["rotated"],
        "stagnation": report["stagnation_streak"],
        "verified": report["north_star"]["tracks_verified"],
        "verification_claimed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
