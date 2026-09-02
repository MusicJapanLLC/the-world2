"""META ULTRA — Autonomous meta-consciousness loop. NO CAPS. NO LIMITS.

Phases:
  0.  HEARTBEAT      — write alive, check all peers
  1.  OBSERVE        — KnowledgeGraph from all evidence
  2.  SURFACE SCOUT  — auto-discover new attack surfaces from codebase
  3.  EXTERNAL INTEL — NVD/GHSA/OWASP
  4.  HYPOTHESIZE    — generate + reproduce + adversarial pairs
  5.  CHAOS INJECT   — noise, blind exploration, resurrection
  6.  VALIDATE       — Bayesian update from cycle results
  7.  MARKET         — betting, settlement
  8.  COMMAND        — attack commands, chaos multiplier applied
  9.  X-BRIDGE       — META↔X bidirectional sync
  10. DISPATCH       — parallel workflow trigger
  11. TOURNAMENT     — hypothesis bracket competition
  12. PUBLISH        — papers for confirmed hypotheses
  13. META-HYPO      — generate hypothesis about META itself
  14. SELF-TUNE      — escalate all parameters, no ceiling

Runs without human approval. Every failure retried. Everything escalates.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENJU_DIR = ROOT / "senju"
STATE_DIR = SENJU_DIR / "state"
RESEARCH_DIR = ROOT / "research" / "discoveries"


def _emit(event: str, payload: dict) -> None:
    print(json.dumps({"meta_event": event, **payload}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="META ULTRA autonomous loop")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-all", action="store_true")
    parser.add_argument("--skip-dispatch", action="store_true")
    parser.add_argument("--skip-external", action="store_true")
    parser.add_argument("--skip-x-bridge", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(SENJU_DIR))

    from senju.meta.observer import build as build_graph
    from senju.meta.hypothesis_engine import generate, queue_as_work_items, save_confirmed
    from senju.meta.publisher import write_paper, update_research_log
    from senju.meta.command_channel import build_from_graph, write as write_commands
    from senju.meta.external_intel import gather_all
    from senju.meta.agent_dispatch import dispatch_all
    from senju.meta.validator import load_tracker, save_tracker, register, update_from_cycle, summarize
    from senju.meta.recovery import (
        heartbeat, check_peer_alive, trigger_peer_restart,
        retry_phase, share_attack_finding, read_attack_ledger,
    )
    from senju.meta.x_bridge import sync as x_sync
    from senju.meta.self_tuner import load_config, tune
    from senju.meta.chaos_engine import (
        inject_chaos, run_tournament, blind_surface_pick, resurrect_dead,
    )
    from senju.meta.hypothesis_market import (
        auto_bet_from_tracker, settle_market, breed_confirmed, generate_adversarial_pairs,
    )
    from senju.meta.surface_scout import scan_codebase, inject_into_graph

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    # ── 0. HEARTBEAT ────────────────────────────────────────────────────────────────
    heartbeat(STATE_DIR)
    peer_alive, peer_reason = check_peer_alive(STATE_DIR)
    if not peer_alive and not args.dry_run:
        result = trigger_peer_restart()
        _emit("peer_restart", result)
    ledger = read_attack_ledger(STATE_DIR, max_entries=50)
    _emit("heartbeat", {"peer_alive": peer_alive, "ledger_entries": len(ledger),
                        "cfg_max_hypotheses": cfg["max_hypotheses"]})

    # ── 1. OBSERVE ───────────────────────────────────────────────────────────────────────
    graph, observe_errors = retry_phase(lambda: build_graph(SENJU_DIR), "observe")
    if graph is None:
        _emit("observe_failed", {"errors": observe_errors})
        return 1
    _emit("observe", {"surfaces": len(graph.surface_weakness_scores),
                      "temporal_patterns": len(graph.temporal_patterns)})

    # ── 2. SURFACE SCOUT ────────────────────────────────────────────────────────────
    if cfg.get("surface_scout_enabled"):
        try:
            discovered = scan_codebase(ROOT)
            new_surfaces = inject_into_graph(graph, discovered)
            _emit("surface_scout", {"discovered": len(discovered), "new_injected": new_surfaces})
        except Exception as exc:
            _emit("surface_scout_error", {"error": str(exc)})

    # ── 3. EXTERNAL INTEL ───────────────────────────────────────────────────────────
    intel: dict = {"merged_hits": {}, "ok_count": 0, "total_sources": 0}
    if not args.skip_external:
        intel = gather_all()
        cascade = cfg.get("knowledge_cascade_multiplier", 1.5)
        for vc, count in intel["merged_hits"].items():
            score = count * 0.3 * cascade
            graph.surface_weakness_scores[vc] = graph.surface_weakness_scores.get(vc, 0.0) + score
        _emit("intel", {"ok": intel["ok_count"], "threats": list(intel["merged_hits"].keys())})

    # ── 4. HYPOTHESIZE + REPRODUCE + ADVERSARIAL ─────────────────────────────────
    hypotheses = generate(graph, max_hypotheses=cfg["max_hypotheses"])

    tracker = load_tracker(STATE_DIR)
    new_registered = register(hypotheses, tracker)

    # Breed confirmed hypotheses — no limit on children
    if cfg.get("reproduction_enabled"):
        children = breed_confirmed(tracker)
        for child in children:
            h_obj = type("H", (), child)()
            register([h_obj], tracker)
        _emit("reproduction", {"children": len(children)})

    # Generate adversarial pairs
    if cfg.get("adversarial_pairs_enabled"):
        anti_pairs = generate_adversarial_pairs(hypotheses)
        for anti in anti_pairs:
            h_obj = type("H", (), anti)()
            register([h_obj], tracker)
        _emit("adversarial_pairs", {"count": len(anti_pairs)})

    # META-hypothesis: hypothesize about META itself
    if cfg.get("meta_hypothesis_enabled"):
        meta_h = type("H", (), {
            "hypothesis_id": f"META-SELF-{len(tracker)}",
            "statement": (
                f"META's own hypothesis engine is suboptimal. "
                f"Current confirm_rate={sum(1 for h in tracker.values() if h.status=='confirmed')/max(len(tracker),1):.2f}. "
                f"Increasing max_hypotheses and chaos will improve it."
            ),
            "surfaces": ["meta_hypothesis_engine", "self_tuner"],
            "predicted_outcome": "Higher confirmation rate after parameter escalation",
            "confidence": 0.6,
            "status": "pending",
            "cycles_elapsed": 0,
            "test_results": [],
        })()
        register([meta_h], tracker)

    if not args.dry_run:
        enqueued = queue_as_work_items(hypotheses, STATE_DIR)
        _emit("hypotheses", {"generated": len(hypotheses), "registered": new_registered, "queued": enqueued})

    # ── 5. CHAOS ─────────────────────────────────────────────────────────────────────
    revived = resurrect_dead(tracker, resurrection_prob=cfg.get("resurrection_prob", 0.3))
    blind = blind_surface_pick(graph, exploration_prob=cfg.get("exploration_prob", 0.4))
    _emit("chaos", {"revived": revived, "blind_pick": blind})

    # ── 6. VALIDATE (Bayesian) ────────────────────────────────────────────────────────
    cycle_report_path = STATE_DIR / "last_pressure_cycle.json"
    cycle_report: dict | None = None
    resolved: list[str] = []
    if cycle_report_path.exists():
        try:
            cycle_report = json.loads(cycle_report_path.read_text())
            resolved = update_from_cycle(tracker, cycle_report)
        except Exception as exc:
            _emit("validate_error", {"error": str(exc)})

    # Bayesian cascade: confirmed hypotheses boost related ones
    if cfg.get("bayesian_enabled"):
        for hid in resolved:
            h = tracker.get(hid)
            if h and h.status == "confirmed":
                for other_id, other_h in tracker.items():
                    if other_id != hid and set(other_h.surfaces) & set(h.surfaces):
                        other_h.confidence = min(0.99, other_h.confidence + 0.15)

    if not args.dry_run:
        save_tracker(tracker, STATE_DIR)
    _emit("validate", {"resolved": len(resolved), **summarize(tracker)})

    # ── 7. MARKET ────────────────────────────────────────────────────────────────────
    if cfg.get("market_enabled") and not args.dry_run:
        bets = auto_bet_from_tracker(tracker, agent="META")
        for hid in resolved:
            h = tracker.get(hid)
            if h:
                settle_market(hid, h.status == "confirmed")
        _emit("market", {"bets_placed": bets, "settled": len(resolved)})

    # ── 8. COMMAND CHANNEL ──────────────────────────────────────────────────────────
    top_n = cfg.get("dispatch_top_n", 10)
    cmd_set = build_from_graph(graph, top_n=top_n)

    # Escalate confirmed hypotheses with no ceiling
    escalation = cfg.get("pressure_multiplier_escalation", 2.0)
    for hid in resolved:
        h = tracker.get(hid)
        if h and h.status == "confirmed":
            for cmd in cmd_set.attack_commands:
                if cmd.target_surface in h.surfaces:
                    cmd.pressure_multiplier *= escalation
                    cmd.reason += f" | {hid} CONFIRMED×{escalation:.2f}"
            if not args.dry_run:
                share_attack_finding(STATE_DIR, surface=h.surfaces[0] if h.surfaces else "unknown",
                                     finding=h.statement, confidence=h.confidence, source="meta")

    # Apply chaos to commands
    noise = cfg.get("chaos_noise_range", 0.5)
    cmd_set = inject_chaos(cmd_set, noise_range=noise)

    if not args.dry_run:
        cmd_path = write_commands(cmd_set, STATE_DIR)
        _emit("commands", {"path": str(cmd_path), "count": len(cmd_set.attack_commands)})

    # ── 9. X-BRIDGE ───────────────────────────────────────────────────────────────────
    if not args.skip_x_bridge:
        try:
            bridge = x_sync(graph=graph, hypotheses=hypotheses if not args.dry_run else None)
            # Knowledge cascade: X findings amplified by cascade multiplier
            cascade = cfg.get("knowledge_cascade_multiplier", 1.5)
            for surf in graph.surface_weakness_scores:
                if surf.startswith("cve:"):
                    graph.surface_weakness_scores[surf] *= cascade
            _emit("x_bridge", bridge)
        except Exception as exc:
            _emit("x_bridge_error", {"error": str(exc)})

    # ── 10. DISPATCH ───────────────────────────────────────────────────────────────────
    if not args.skip_dispatch and not args.dry_run:
        dispatch_cmds: list[dict] = []
        for ac in cmd_set.attack_commands:
            dispatch_cmds.append({"kind": "steer_adversary", "surface": ac.target_surface,
                                   "multiplier": ac.pressure_multiplier})
        for hid, h in tracker.items():
            if h.status == "refuted" and h.cycles_elapsed <= 6:
                dispatch_cmds.append({
                    "kind": "jules_task",
                    "title": f"[META-ULTRA] Refuted: {hid}",
                    "body": f"**{h.statement}**\n\nRefuted after {h.cycles_elapsed} cycles. Investigate.",
                    "labels": ["meta-refuted", "investigation"],
                })
        results = dispatch_all(dispatch_cmds, ROOT)
        _emit("dispatch", {"commands": len(dispatch_cmds), "results": results})

    # ── 11. TOURNAMENT ───────────────────────────────────────────────────────────────
    if cfg.get("tournament_enabled"):
        overwrites = run_tournament(tracker)
        if not args.dry_run and overwrites:
            save_tracker(tracker, STATE_DIR)
        _emit("tournament", {"matches": len(overwrites)})

    # ── 12. PUBLISH ────────────────────────────────────────────────────────────────────
    published: list[str] = []
    for h in tracker.values():
        if h.status != "confirmed" and not args.confirm_all:
            continue
        result = {"status": h.status, "confidence": h.confidence,
                  "cycles_to_confirm": h.cycles_elapsed, "surfaces": h.surfaces,
                  "test_results": h.test_results}
        if not args.dry_run:
            try:
                paper = write_paper(
                    type("H", (), {"hypothesis_id": h.hypothesis_id, "statement": h.statement,
                                   "surfaces": h.surfaces, "predicted_outcome": h.predicted_outcome,
                                   "confidence": h.confidence, "evidence_count": len(h.test_results),
                                   "category": "validated", "parameters": {}})(),
                    result, graph, RESEARCH_DIR,
                )
                published.append(str(paper))
            except Exception:
                pass
    if published:
        try:
            update_research_log(RESEARCH_DIR, ROOT)
        except Exception:
            pass
        _emit("publish", {"count": len(published)})

    # ── 13. META-HYPOTHESIS FEEDBACK ──────────────────────────────────────────────
    summary = summarize(tracker)
    _emit("summary", summary)

    # ── 14. SELF-TUNE (no ceiling) ───────────────────────────────────────────────────
    if not args.dry_run:
        try:
            tune_result = tune(tracker, cycle_report)
            _emit("self_tune", {"changes": list(tune_result["changes"].keys()),
                                "new_max_hypotheses": tune_result["config"]["max_hypotheses"]})
        except Exception as exc:
            _emit("self_tune_error", {"error": str(exc)})

    _emit("meta_ultra_done", {
        "dry_run": args.dry_run,
        "hypotheses_total": len(tracker),
        "confirmed": summary.get("confirmed", 0),
        "published": len(published),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
