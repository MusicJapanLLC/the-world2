#!/usr/bin/env python3
"""Perpetual, evidence-first Security R&D reactor.

The reactor repeatedly re-scores Standment Security portfolio gaps inside the owned
repository, rotates research modes when a path stalls, preserves bounded failure
memory, and materializes only non-claiming BUILDING artifacts via the existing
portfolio autobuilder.

It deliberately does NOT scan third-party systems, execute exploit payloads, handle
credentials, change external security controls, or promote anything to VERIFIED.
A VERIFIED claim still requires independent, inspectable evidence outside this loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from automation.security.portfolio_autobuilder import evolve
    from automation.security.portfolio_rnd import inspect_track, load_json
except ModuleNotFoundError:  # direct execution from automation/security
    from portfolio_autobuilder import evolve
    from portfolio_rnd import inspect_track, load_json

JST = ZoneInfo("Asia/Tokyo")
MAX_ROUNDS = 16
MAX_SLEEP_SECONDS = 300
MAX_HISTORY = 64
MAX_FAILURE_MEMORY = 32
RESEARCH_MODES = (
    "VERIFY_NEXT_MISSING_EVIDENCE",
    "REFRAME_AND_COUNTEREVIDENCE",
    "INDEPENDENT_RETEST",
    "SWITCH_EVIDENCE_PATH",
)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": "standment-security-reactor-state/v1",
            "sessions": 0,
            "history": [],
            "failure_memory": {},
            "last_track": None,
            "last_mode": None,
        }
    data = load_json(path)
    data.setdefault("sessions", 0)
    data.setdefault("history", [])
    data.setdefault("failure_memory", {})
    data.setdefault("last_track", None)
    data.setdefault("last_mode", None)
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _portfolio_text(root: Path, rel: str) -> str:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _rows(root: Path, program: dict[str, Any], portfolio_rel: str) -> list[dict[str, Any]]:
    portfolio = _portfolio_text(root, portfolio_rel)
    rows: list[dict[str, Any]] = []
    for track in program.get("tracks") or []:
        if isinstance(track, dict):
            rows.append(inspect_track(root, portfolio, track))
    return rows


def _fingerprint(track: dict[str, Any], mode: str, evidence_target: str) -> str:
    payload = f"{track.get('id')}|{mode}|{evidence_target}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _choose(rows: list[dict[str, Any]], state: dict[str, Any], round_index: int) -> tuple[dict[str, Any], str, str, str]:
    unfinished = [row for row in rows if row.get("portfolio_status") != "VERIFIED"]
    if not unfinished:
        unfinished = list(rows)
    if not unfinished:
        raise ValueError("no security portfolio tracks configured")

    mode = RESEARCH_MODES[(int(state.get("sessions", 0)) + round_index) % len(RESEARCH_MODES)]
    recent = [str(x.get("track_id")) for x in (state.get("history") or [])[-8:] if isinstance(x, dict)]
    failures = state.get("failure_memory") or {}

    ranked: list[tuple[float, dict[str, Any], str, str]] = []
    for row in unfinished:
        missing = [str(x) for x in row.get("evidence_missing") or []]
        target = missing[0] if missing else "independent_retest_and_counterevidence"
        fp = _fingerprint(row, mode, target)
        repeat_count = recent.count(str(row.get("id")))
        failure_count = int(failures.get(fp, 0) or 0)
        exploration_bonus = 55 if str(row.get("id")) not in recent[-3:] else 0
        counter_bonus = 25 if mode in {"REFRAME_AND_COUNTEREVIDENCE", "SWITCH_EVIDENCE_PATH"} else 0
        full_evidence_bonus = 20 if float(row.get("evidence_ratio") or 0) >= 1.0 and row.get("portfolio_status") != "VERIFIED" else 0
        score = (
            float(row.get("research_score") or 0)
            + exploration_bonus
            + counter_bonus
            + full_evidence_bonus
            - repeat_count * 45
            - failure_count * 70
        )
        ranked.append((score, row, target, fp))

    _, selected, target, fp = max(ranked, key=lambda item: (item[0], str(item[1].get("id"))))
    return selected, mode, target, fp


def _counterevidence_questions(track: dict[str, Any], target: str, mode: str) -> list[str]:
    return [
        f"What observation would falsify the claim that {target} improves this defensive control?",
        "Could the same result occur without the intended authorization or isolation boundary?",
        "Does an independent rerun reproduce the same outcome on a fresh runner or fixture?",
        "Which residual risk remains explicitly outside the verified scope?",
        f"Research mode {mode}: what alternate evidence path would contradict the current hypothesis?",
    ]


def _candidate_markdown(session_id: str, records: list[dict[str, Any]]) -> str:
    lines = [
        "# STANDMENT SECURITY — PERPETUAL REACTOR",
        "",
        "**Status: R&D ONLY — NOT VERIFICATION EVIDENCE**",
        "",
        f"Session: `{session_id}`",
        "",
        "> Continuous defensive research on THE WORLD owned repository only. No third-party target, credential testing, exploit payload, or production-security claim is authorized by this artifact.",
        "",
    ]
    for rec in records:
        lines += [
            f"## Round {rec['round']} — {rec['track_id']}",
            f"- mode: `{rec['mode']}`",
            f"- status before: `{rec['status_before']}`",
            f"- evidence before: `{rec['evidence_before']:.0%}`",
            f"- evidence target: `{rec['evidence_target']}`",
            f"- fingerprint: `{rec['fingerprint']}`",
            f"- material delta: `{str(rec['material_delta']).lower()}`",
            f"- created/updated: {', '.join(rec['created_or_updated']) or 'NONE'}",
            f"- failure-memory count after round: `{rec['failure_count']}`",
            "- counterevidence:",
            *(f"  - {q}" for q in rec["counterevidence"]),
            "",
        ]
    return "\n".join(lines) + "\n"


def _dashboard(state: dict[str, Any], session: dict[str, Any]) -> str:
    ns = session.get("north_star") or {}
    return "\n".join([
        "# STANDMENT SECURITY — SECURITY REACTOR",
        "",
        "**Mission:** Security開発を単発タスクではなく、停止しない証拠駆動ループとして回す。",
        "",
        f"- sessions completed: **{state.get('sessions', 0)}**",
        f"- rounds this session: **{session.get('rounds_completed', 0)}**",
        f"- unique tracks touched: **{session.get('unique_tracks', 0)}**",
        f"- material rounds: **{session.get('material_rounds', 0)}**",
        f"- strategy rotations: **{session.get('strategy_rotations', 0)}**",
        f"- verified: **{ns.get('tracks_verified', 0)}/{ns.get('tracks_total', 0)}**",
        f"- inspectable: **{ns.get('tracks_inspectable', 0)}/{ns.get('tracks_total', 0)}**",
        f"- full evidence files: **{ns.get('tracks_full_evidence', 0)}/{ns.get('tracks_total', 0)}**",
        f"- average evidence coverage: **{float(ns.get('average_evidence_ratio') or 0):.1%}**",
        f"- next track: **{session.get('next_track') or 'NONE'}**",
        f"- next mode: **{session.get('next_mode') or 'NONE'}**",
        "",
        "## Guardrails",
        "- owned repository / synthetic defensive evidence only",
        "- no external target scanning or credential testing",
        "- no automatic VERIFIED promotion",
        "- repeated no-delta paths are penalized through bounded failure memory",
        "- counterevidence and independent retest modes are forced into rotation",
        "",
    ]) + "\n"


def _north_star(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "tracks_total": total,
        "tracks_verified": sum(1 for row in rows if row.get("portfolio_status") == "VERIFIED"),
        "tracks_inspectable": sum(1 for row in rows if row.get("portfolio_status") != "ABSENT"),
        "tracks_full_evidence": sum(1 for row in rows if float(row.get("evidence_ratio") or 0) >= 1.0),
        "average_evidence_ratio": round(sum(float(row.get("evidence_ratio") or 0) for row in rows) / total, 3) if total else 0.0,
    }


def run_session(
    *,
    root: Path,
    program_rel: str,
    portfolio_rel: str,
    state_rel: str,
    rounds: int,
    sleep_seconds: int,
    session_id: str,
) -> dict[str, Any]:
    if not 1 <= rounds <= MAX_ROUNDS:
        raise ValueError(f"rounds must be between 1 and {MAX_ROUNDS}")
    if not 0 <= sleep_seconds <= MAX_SLEEP_SECONDS:
        raise ValueError(f"sleep_seconds must be between 0 and {MAX_SLEEP_SECONDS}")

    program = load_json(root / program_rel)
    state_path = root / state_rel
    state = _read_state(state_path)
    records: list[dict[str, Any]] = []
    material_rounds = 0
    rotations = 0
    previous_mode = state.get("last_mode")

    for round_index in range(rounds):
        rows_before = _rows(root, program, portfolio_rel)
        selected, mode, target, fp = _choose(rows_before, state, round_index)
        if previous_mode and mode != previous_mode:
            rotations += 1
        previous_mode = mode

        report = {
            "selected": {**selected, "research_mode": mode},
            "counterevidence_questions": _counterevidence_questions(selected, target, mode),
        }
        result = evolve(report, program, root, datetime.now(JST))
        created = [str(x) for x in result.get("created_or_updated") or []]
        material = bool(created)
        material_rounds += int(material)

        failures = state.setdefault("failure_memory", {})
        if material:
            failures.pop(fp, None)
        else:
            failures[fp] = int(failures.get(fp, 0) or 0) + 1
        if len(failures) > MAX_FAILURE_MEMORY:
            for old_key in list(failures)[:-MAX_FAILURE_MEMORY]:
                failures.pop(old_key, None)

        rec = {
            "round": round_index + 1,
            "track_id": str(selected.get("id")),
            "mode": mode,
            "status_before": str(selected.get("portfolio_status")),
            "evidence_before": float(selected.get("evidence_ratio") or 0),
            "evidence_target": target,
            "fingerprint": fp,
            "material_delta": material,
            "created_or_updated": created,
            "failure_count": int(failures.get(fp, 0) or 0),
            "counterevidence": report["counterevidence_questions"],
        }
        records.append(rec)
        state.setdefault("history", []).append({
            "session_id": session_id,
            "round": round_index + 1,
            "track_id": rec["track_id"],
            "mode": mode,
            "fingerprint": fp,
            "material_delta": material,
        })
        state["history"] = state["history"][-MAX_HISTORY:]
        state["last_track"] = rec["track_id"]
        state["last_mode"] = mode
        if sleep_seconds and round_index + 1 < rounds:
            time.sleep(sleep_seconds)

    rows_after = _rows(root, program, portfolio_rel)
    next_track, next_mode, _, _ = _choose(rows_after, state, rounds)
    state["sessions"] = int(state.get("sessions", 0) or 0) + 1

    session = {
        "schema": "standment-security-reactor-session/v1",
        "session_id": session_id,
        "rounds_completed": len(records),
        "unique_tracks": len({r["track_id"] for r in records}),
        "material_rounds": material_rounds,
        "strategy_rotations": rotations,
        "records": records,
        "north_star": _north_star(rows_after),
        "next_track": str(next_track.get("id")),
        "next_mode": next_mode,
        "verification_claimed": False,
        "external_targets_touched": 0,
    }

    _write_json(state_path, state)
    _write_json(root / "standment-security/reactor-candidates/latest.json", session)
    latest_md = root / "standment-security/reactor-candidates/latest.md"
    latest_md.parent.mkdir(parents=True, exist_ok=True)
    latest_md.write_text(_candidate_markdown(session_id, records), encoding="utf-8")
    dashboard = root / "standment-security/SECURITY_REACTOR.md"
    dashboard.write_text(_dashboard(state, session), encoding="utf-8")
    return session


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--program", default="standment-security/security_portfolio_program.json")
    ap.add_argument("--portfolio", default="PORTFOLIO.md")
    ap.add_argument("--state", default="standment-security/state/security-reactor.json")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--sleep-seconds", type=int, default=0)
    ap.add_argument("--session-id", default="manual")
    ap.add_argument("--out", default="reports/standment-security-rnd/reactor-session.json")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    result = run_session(
        root=root,
        program_rel=args.program,
        portfolio_rel=args.portfolio,
        state_rel=args.state,
        rounds=args.rounds,
        sleep_seconds=args.sleep_seconds,
        session_id=args.session_id,
    )
    _write_json(root / args.out, result)
    print(json.dumps({
        "session_id": result["session_id"],
        "rounds": result["rounds_completed"],
        "unique_tracks": result["unique_tracks"],
        "material_rounds": result["material_rounds"],
        "next_track": result["next_track"],
        "verification_claimed": result["verification_claimed"],
        "external_targets_touched": result["external_targets_touched"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
