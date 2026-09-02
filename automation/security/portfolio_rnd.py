#!/usr/bin/env python3
"""Portfolio-first R&D planner for Standment Security.

The planner is evidence-first, defensive, and target-free. It ranks portfolio
gaps, compares today's state with the previous successful run, detects stagnation,
and emits the next bounded R&D brief plus a human-readable Slack delta.

It does not scan third-party systems, change external security controls, or treat
technical evidence as market validation.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_SENJU_FOCUS = {"robustness", "learning", "balance", "efficiency"}

PORTFOLIO_MARKERS = {
    "SEC-PORT-001": "## 3. Standment Security Scan v1",
    "SEC-PORT-002": "## Standment Security Evidence Pack",
    "SEC-PORT-003": "## Standment Security Supply-Chain Evidence Portfolio",
    "SEC-PORT-004": "## Standment Security Auth / Tenant / RLS Evidence Kit",
    "SEC-PORT-005": "## Standment Autonomous-Agent Security & Auditability Pack",
    "SEC-PORT-006": "## Standment Incident Readiness & Recovery Evidence Pack",
    "SEC-PORT-007": "## Standment Continuous Security Retainer Scorecard",
    "SEC-PORT-008": "## Standment Security Architecture Review Pack",
    "SEC-PORT-009": "## AI Agent Permission Boundary Lab",
    "SEC-PORT-010": "## LLM Security Evaluation Harness",
    "SEC-PORT-011": "## Standment Security Evidence Dashboard",
}

ARTIFACT_STATUS_FILES = {
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

STATUS_LEVEL = {
    "ABSENT": 0,
    "EXPERIMENT": 1,
    "VISIBLE": 1,
    "BUILDING": 2,
    "BLOCKED": 2,
    "PROMOTION_READY": 3,
    "VERIFIED": 4,
}

STATUS_RE = re.compile(
    r"(?:状態|Status)\s*:\s*\*\*?\s*(ABSENT|EXPERIMENT|VISIBLE|BUILDING|BLOCKED|PROMOTION_READY|VERIFIED)",
    re.I,
)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data


def section_status(portfolio: str, marker: str) -> str:
    """Return status from exactly one markdown H2 section."""
    lower = portfolio.lower()
    pos = lower.find(marker.lower())
    if pos < 0:
        return "ABSENT"

    section_start = portfolio.rfind("\n## ", 0, pos + 1)
    if section_start < 0:
        section_start = pos
    else:
        section_start += 1

    next_h2 = portfolio.find("\n## ", max(pos + len(marker), section_start + 3))
    section_end = len(portfolio) if next_h2 < 0 else next_h2
    section = portfolio[section_start:section_end]

    for status in ("VERIFIED", "PROMOTION_READY", "BUILDING", "EXPERIMENT", "BLOCKED"):
        if f"状態: {status}" in section or f"**状態: {status}**" in section:
            return status
    return "VISIBLE"


def artifact_status(root: Path, track_id: str) -> str:
    """Read maturity from the customer-inspectable track artifact when present."""
    rel = ARTIFACT_STATUS_FILES.get(track_id)
    if not rel:
        return "ABSENT"
    path = root / rel
    if not path.exists():
        return "ABSENT"
    text = path.read_text(encoding="utf-8", errors="replace")[:16000]
    match = STATUS_RE.search(text)
    return match.group(1).upper() if match else "VISIBLE"


def inspect_track(root: Path, portfolio: str, track: dict[str, Any]) -> dict[str, Any]:
    track_id = str(track.get("id", ""))
    focus = str(track.get("senju_focus", ""))
    if focus not in ALLOWED_SENJU_FOCUS:
        raise ValueError(f"{track_id}: invalid senju focus {focus!r}")

    evidence_files = [str(x) for x in track.get("evidence_files", [])]
    present = [p for p in evidence_files if (root / p).exists()]
    missing = [p for p in evidence_files if not (root / p).exists()]
    ratio = (len(present) / len(evidence_files)) if evidence_files else 0.0
    marker = PORTFOLIO_MARKERS.get(track_id, str(track.get("title", "")))
    portfolio_status = section_status(portfolio, marker)
    direct_artifact_status = artifact_status(root, track_id)
    status = max(
        (portfolio_status, direct_artifact_status),
        key=lambda candidate: STATUS_LEVEL.get(candidate, 0),
    )

    status_gap = {
        "ABSENT": 180,
        "EXPERIMENT": 150,
        "BUILDING": 100,
        "BLOCKED": 130,
        "VISIBLE": 90,
        "PROMOTION_READY": 55,
        "VERIFIED": 20,
    }.get(status, 100)
    evidence_gap = round((1.0 - ratio) * 120)
    priority = int(track.get("priority", 0) or 0)
    research_score = priority + status_gap + evidence_gap

    return {
        "id": track_id,
        "title": str(track.get("title", "")),
        "priority": priority,
        "research_score": research_score,
        "portfolio_status": status,
        "portfolio_index_status": portfolio_status,
        "artifact_status": direct_artifact_status,
        "evidence_ratio": round(ratio, 3),
        "evidence_present": present,
        "evidence_missing": missing,
        "senju_focus": focus,
        "hypothesis": str(track.get("hypothesis", "")),
        "deliverable": str(track.get("deliverable", "")),
        "customer_usefulness": str(track.get("customer_usefulness", "")),
    }


def choose_track(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("no security portfolio tracks configured")
    return sorted(
        rows,
        key=lambda x: (int(x["research_score"]), int(x["priority"]), str(x["id"])),
        reverse=True,
    )[0]


def _state(track: dict[str, Any] | None, promotion_ready: bool | None = None) -> dict[str, Any]:
    if not track:
        return {
            "track_id": None,
            "status": "NO_BASELINE",
            "evidence_ratio": None,
            "evidence_count": 0,
            "promotion_ready": None,
        }
    return {
        "track_id": track.get("id"),
        "status": track.get("portfolio_status"),
        "evidence_ratio": track.get("evidence_ratio"),
        "evidence_count": len(track.get("evidence_present") or []),
        "promotion_ready": promotion_ready,
    }


def compare_previous(
    previous: dict[str, Any] | None,
    selected: dict[str, Any],
    promotion_ready: bool,
) -> dict[str, Any]:
    previous_selected = (previous or {}).get("selected") or {}
    previous_promotion = (previous or {}).get("promotion_ready")
    same_track = previous_selected.get("id") == selected.get("id")

    before = _state(previous_selected or None, previous_promotion)
    after = _state(selected, promotion_ready)

    newly_present: list[str] = []
    lost_evidence: list[str] = []
    status_changed = False
    evidence_delta = None
    promotion_changed = False

    if previous_selected:
        if same_track:
            old_present = set(previous_selected.get("evidence_present") or [])
            new_present = set(selected.get("evidence_present") or [])
            newly_present = sorted(new_present - old_present)
            lost_evidence = sorted(old_present - new_present)
            old_ratio = float(previous_selected.get("evidence_ratio") or 0.0)
            new_ratio = float(selected.get("evidence_ratio") or 0.0)
            evidence_delta = round(new_ratio - old_ratio, 3)
            status_changed = previous_selected.get("portfolio_status") != selected.get("portfolio_status")
            promotion_changed = bool(previous_promotion) != bool(promotion_ready)
        else:
            evidence_delta = None

    material_delta = bool(
        previous_selected
        and same_track
        and (
            status_changed
            or promotion_changed
            or (evidence_delta is not None and abs(evidence_delta) > 1e-9)
            or newly_present
            or lost_evidence
        )
    )

    if not previous_selected:
        delta_kind = "BASELINE_CAPTURED"
    elif not same_track:
        delta_kind = "RESEARCH_REFOCUS"
    elif material_delta:
        delta_kind = "VERIFIED_PORTFOLIO_DELTA"
    else:
        delta_kind = "NO_VERIFIED_DELTA"

    previous_streak = int((previous or {}).get("stagnation_streak", 0) or 0)
    if delta_kind == "NO_VERIFIED_DELTA":
        stagnation_streak = previous_streak + 1
    else:
        stagnation_streak = 0

    if stagnation_streak >= 3:
        research_mode = "SWITCH_EVIDENCE_PATH"
    elif stagnation_streak >= 2:
        research_mode = "REFRAME_AND_COUNTEREVIDENCE"
    elif stagnation_streak >= 1:
        research_mode = "VERIFY_NEXT_MISSING_EVIDENCE"
    else:
        research_mode = "NORMAL"

    return {
        "kind": delta_kind,
        "same_track": same_track,
        "material_delta": material_delta,
        "before": before,
        "after": after,
        "status_changed": status_changed,
        "evidence_delta": evidence_delta,
        "new_evidence": newly_present,
        "lost_evidence": lost_evidence,
        "promotion_changed": promotion_changed,
        "stagnation_streak": stagnation_streak,
        "research_mode": research_mode,
    }


def build_north_star(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    verified = sum(1 for r in rows if r["portfolio_status"] == "VERIFIED")
    inspectable = sum(1 for r in rows if r["portfolio_status"] != "ABSENT")
    full_evidence = sum(1 for r in rows if float(r["evidence_ratio"]) >= 1.0)
    average_evidence = (
        round(sum(float(r["evidence_ratio"]) for r in rows) / total, 3)
        if total
        else 0.0
    )
    return {
        "tracks_total": total,
        "tracks_inspectable": inspectable,
        "tracks_verified": verified,
        "tracks_full_evidence": full_evidence,
        "average_evidence_ratio": average_evidence,
        "unfinished_tracks": total - verified,
    }


def build_senju_item(selected: dict[str, Any]) -> dict[str, Any]:
    missing = selected.get("evidence_missing") or []
    research_mode = str(selected.get("research_mode") or "NORMAL")
    gap = (
        "Missing repository evidence: " + ", ".join(missing)
        if missing
        else f"Portfolio maturity is {selected['portfolio_status']}; strengthen reproducibility and customer-facing proof."
    )
    mode_instruction = {
        "NORMAL": "Continue the highest-value evidence path.",
        "VERIFY_NEXT_MISSING_EVIDENCE": "Prioritize the smallest independently verifiable missing evidence item.",
        "REFRAME_AND_COUNTEREVIDENCE": "Reframe the hypothesis and actively seek counterevidence before repeating the same path.",
        "SWITCH_EVIDENCE_PATH": "Switch to an alternate evidence path or verification method; do not repeat an unchanged experiment.",
    }.get(research_mode, "Continue with bounded defensive evidence generation.")

    return {
        "research_id": f"RND-STANDMENT-{selected['id']}",
        "title": f"Standment Security portfolio process: {selected['title']}",
        "problem": f"{gap} Research mode={research_mode}. {mode_instruction}"[:700],
        "hypothesis": (
            f"{selected['hypothesis']} Daily improvement rule: {mode_instruction}"
        )[:600],
        "focus": selected["senju_focus"],
        "priority": 1000 + int(selected["priority"]),
        "candidate_count": 9,
        "success": {
            "safe": True,
            "stable": True,
            "holdout_required": True,
            "worst_score_positive": True,
            "worst_balance_min": 0.35,
            "worst_learning_min": 0.05,
            "score_stdev_max": 35.0,
        },
        "commercial_bridge": (
            "Use Senju only to improve the reliability/reproducibility of the research process. "
            "Promotion to portfolio still requires a human-inspectable artifact and real verification evidence; "
            "technical scores do not prove buyer demand, contracts, payments, or revenue."
        ),
    }


def build_report(
    program: dict[str, Any],
    root: Path,
    portfolio: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tracks = program.get("tracks") or []
    rows = [inspect_track(root, portfolio, t) for t in tracks if isinstance(t, dict)]
    selected = choose_track(rows)
    gate = program.get("promotion_gate") or {}
    promotion_ready = (
        selected["portfolio_status"] == "VERIFIED"
        and selected["evidence_ratio"] >= 1.0
        and bool(gate.get("human_inspectable_artifact_required"))
        and bool(gate.get("verification_evidence_required", True))
        and bool(gate.get("counterevidence_required", True))
        and bool(gate.get("reproducibility_required", True))
    )

    delta = compare_previous(previous, selected, promotion_ready)
    selected["research_mode"] = delta["research_mode"]

    north_star = build_north_star(rows)
    report_key = (
        f"{selected['id']}:{selected['portfolio_status']}:"
        f"{round(float(selected['evidence_ratio']) * 100)}:{int(promotion_ready)}:"
        f"{delta['stagnation_streak']}"
    )

    if delta["kind"] == "VERIFIED_PORTFOLIO_DELTA":
        capability_gain = (
            f"{selected['title']} gained verified portfolio evidence or maturity compared with the previous successful run."
        )
    elif delta["kind"] == "RESEARCH_REFOCUS":
        capability_gain = (
            "No artifact improvement is claimed; the autonomous R&D system changed the primary research target based on the current evidence gap."
        )
    elif delta["kind"] == "BASELINE_CAPTURED":
        capability_gain = (
            "Daily comparison memory is now available for future Before→After evaluation; no portfolio improvement is claimed from the baseline alone."
        )
    else:
        capability_gain = (
            "No new portfolio capability was proven in this cycle. The system detected stagnation and adjusted the next research mode instead of repeating an unchanged claim."
        )

    return {
        "schema": "standment-security-portfolio-rnd-report/v4",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mission": program.get("mission"),
        "reporting_contract": program.get("reporting_contract", "standment-security/REPORTING_CONTRACT.md"),
        "report_key": report_key,
        "portfolio_first": bool(program.get("portfolio_first")),
        "operating_policy": program.get("operating_policy") or {},
        "selected": selected,
        "all_tracks": rows,
        "north_star": north_star,
        "promotion_ready": promotion_ready,
        "promotion_rule": (
            "#portfolio receives only a human-inspectable artifact with verification proof. "
            "Daily research progress belongs in R&D reporting."
        ),
        "delta": delta,
        "stagnation_streak": delta["stagnation_streak"],
        "capability_gain": capability_gain,
        "owner_benefit": (
            "The owner can see whether Standment's security portfolio actually advanced, stalled, or merely changed research direction without reading raw engineering logs."
        ),
        "business_effect": (
            selected.get("customer_usefulness")
            or "Move verified defensive engineering closer to a customer-inspectable, reusable security deliverable."
        ),
        "next_research": build_senju_item(selected),
        "counterevidence_questions": [
            "What evidence would falsify the current hypothesis?",
            "Can an independent run reproduce the result?",
            "Is the artifact understandable without reading source code?",
            "What remains unverified or environment-dependent?",
            "Does the evidence demonstrate technical quality only, rather than market demand?",
        ],
    }


def _fmt_ratio(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.0%}"


def render(report: dict[str, Any]) -> str:
    s = report["selected"]
    d = report["delta"]
    ns = report["north_star"]
    missing = ", ".join(s["evidence_missing"]) or "NONE"
    new_evidence = ", ".join(d.get("new_evidence") or []) or "NONE"
    lost_evidence = ", ".join(d.get("lost_evidence") or []) or "NONE"
    questions = " / ".join(report["counterevidence_questions"][:3])
    promotion = "PASS" if report["promotion_ready"] else "NOT READY"
    before = d["before"]
    after = d["after"]
    delta_value = d.get("evidence_delta")
    delta_text = "N/A" if delta_value is None else f"{delta_value:+.0%}"

    return (
        "*STANDMENT SECURITY｜PORTFOLIO EVOLUTION DAILY*\n"
        f"Report key: `{report['report_key']}` / delta=`{d['kind']}` / research_mode=`{d['research_mode']}`\n\n"
        "*Before → After*\n"
        f"Before: track={before.get('track_id') or 'NONE'} / status={before.get('status')} / evidence={_fmt_ratio(before.get('evidence_ratio'))} / promotion={before.get('promotion_ready')}\n"
        f"After: track={after.get('track_id')} / status={after.get('status')} / evidence={_fmt_ratio(after.get('evidence_ratio'))} / promotion={after.get('promotion_ready')}\n"
        f"Evidence delta: {delta_text} / new={new_evidence} / lost={lost_evidence}\n\n"
        "*何が変わった？*\n"
        f"{report['capability_gain']}\n\n"
        "*実物は何？*\n"
        f"{s['deliverable']}\n\n"
        "*検証結果*\n"
        f"Portfolio promotion gate: {promotion} / Senju bounded focus: {s['senju_focus']} / Missing evidence: {missing}\n"
        f"Status source: index={s.get('portfolio_index_status')} / artifact={s.get('artifact_status')} / resolved={s.get('portfolio_status')}\n"
        f"Stagnation streak: {report['stagnation_streak']} day(s)\n\n"
        "*North Star*\n"
        f"Security tracks: {ns['tracks_total']} / inspectable={ns['tracks_inspectable']} / verified={ns['tracks_verified']} / "
        f"full-evidence={ns['tracks_full_evidence']} / avg evidence={ns['average_evidence_ratio']:.0%}\n\n"
        "*何に使える？*\n"
        f"{report['business_effect']}\n\n"
        "*Owner benefit*\n"
        f"{report['owner_benefit']}\n\n"
        "*失敗・反証*\n"
        f"未充足Evidence: {missing}. Lost evidence: {lost_evidence}. Skeptic gate: {questions}\n\n"
        "*現在ステータス*\n"
        f"{s['portfolio_status']}\n\n"
        "*次に自動でやること*\n"
        f"`{s['id']}` を `{d['research_mode']}` で進める。R&D × Senjuで不足Evidenceを検証し、"
        "同じ主張を繰り返さず、次回runでBefore→Afterを再計測する。\n\n"
        "*Success criteria*\n"
        "人間が開ける成果物 + 独立検証 + 反証保存 + 再現性。VERIFIED昇格には実証済みEvidenceを要求する。\n\n"
        "*Owner action*\nNONE\n\n"
        "> Source codeや自己申告だけではPortfolio成果に昇格しない。技術スコアは市場需要・契約・入金を意味しない。\n"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--program", default="standment-security/security_portfolio_program.json")
    p.add_argument("--portfolio", default="PORTFOLIO.md")
    p.add_argument("--previous", default="")
    p.add_argument("--out", default="reports/standment-security-rnd")
    args = p.parse_args()

    root = Path.cwd()
    program = load_json(root / args.program)
    portfolio = (root / args.portfolio).read_text(encoding="utf-8")

    previous = None
    if args.previous:
        previous_path = Path(args.previous)
        if previous_path.exists():
            previous = load_json(previous_path)

    report = build_report(program, root, portfolio, previous=previous)

    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "daily.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "daily.md").write_text(render(report), encoding="utf-8")
    (out / "senju-research-item.json").write_text(
        json.dumps(report["next_research"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "selected": report["selected"]["id"],
        "research_score": report["selected"]["research_score"],
        "promotion_ready": report["promotion_ready"],
        "senju_focus": report["next_research"]["focus"],
        "report_key": report["report_key"],
        "delta_kind": report["delta"]["kind"],
        "stagnation_streak": report["stagnation_streak"],
        "research_mode": report["delta"]["research_mode"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
