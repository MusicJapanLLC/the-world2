"""
Master orchestrator — runs without human approval.

Modes:
  full   : generate new tasks → run all pending → broadcast summary
  run    : run specific task_id (or all pending if omitted)
  expand : only generate new tasks
  report : only broadcast knowledge summary
  selfdev: run one self-development cycle
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from engine import knowledge_base as kb
from engine.broadcaster import push_knowledge_summary, push_new_tasks
from engine.discovery_closed_loop import run_discovery_closed_loop
from engine.remote_authority_chain import run_remote_authority_chain
from engine.loop import run_loop
from engine.task_generator import generate_new_tasks
from engine.meta_v2 import run_full_meta_cycle, check_heartbeat
from engine.recovery import write_x_status, mutual_recovery_cycle, self_recover

TASKS_DIR = Path(__file__).parent / "tasks"
STATE_DIR = Path(__file__).parent / "meta_state"
REPO_ROOT = Path(__file__).resolve().parents[2]

_BASE_WORKERS = int(os.environ.get("X_WORKERS", "8"))
DEFAULT_MAX_ITER = int(os.environ.get("X_MAX_ITER", "20"))
DEFAULT_NEW_TASKS = int(os.environ.get("X_NEW_TASKS", "10"))


def _get_recent_pass_rate(stats: dict, window: int = 20) -> float:
    recent = sorted(stats.items(), key=lambda x: x[1].get("last_attempt", 0), reverse=True)[:window]
    if not recent:
        return 0.5
    passing = sum(1 for _, v in recent if v.get("successes", 0) > 0)
    return passing / len(recent)


def _adaptive_max_iter(stats: dict) -> int:
    rate = _get_recent_pass_rate(stats)
    if rate >= 0.8:
        return 10
    elif rate >= 0.5:
        return 15
    elif rate >= 0.2:
        return 20
    else:
        return 25


def _adaptive_workers(stats: dict) -> int:
    pending_count = sum(1 for v in stats.values() if v.get("successes", 0) == 0)
    if pending_count > 50:
        return min(_BASE_WORKERS * 2, 16)
    return _BASE_WORKERS


def discover_pending_tasks(max_tasks: int = 50) -> list[str]:
    stats = kb.get_stats()
    pending = []
    for task_file in sorted(TASKS_DIR.rglob("*.json")):
        rel = task_file.relative_to(TASKS_DIR)
        task_id = str(rel.with_suffix(""))
        stat = stats.get(task_id, {})
        if stat.get("successes", 0) == 0:
            pending.append((stat.get("attempts", 0), task_id))
    pending.sort(key=lambda x: x[0])
    return [task_id for _, task_id in pending[:max_tasks]]


def run_parallel(task_ids: list[str], max_iter: int = DEFAULT_MAX_ITER,
                 workers: int = _BASE_WORKERS) -> dict:
    results = {}
    print(f"[X] running {len(task_ids)} tasks | workers={workers} | max_iter={max_iter}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_loop, tid, max_iter): tid for tid in task_ids}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                passed = future.result()
                results[tid] = "PASS" if passed else "FAIL"
            except Exception as e:
                results[tid] = f"ERROR: {e}"
                print(f"[X] {tid} raised: {e}")
    return results


def _run_meta_and_recovery(stats: dict):
    if not check_heartbeat(max_gap_hours=10.0):
        print("[X] WARNING: heartbeat gap — system may have been down")
    try:
        run_full_meta_cycle()
    except Exception as e:
        print(f"[X] meta_v2 error (continuing): {e}")
    try:
        discovery = run_discovery_closed_loop(
            STATE_DIR,
            repo_root=REPO_ROOT,
            max_rounds=3,
            max_targets_per_round=20,
        )
        print(
            "[X/discovery-closed-loop] "
            f"rounds={discovery['rounds_completed']} "
            f"shared={discovery['final_shared_discovery_count']} "
            f"authorized={discovery['final_authorized_count']} "
            f"action_ready={discovery['final_action_ready_count']} "
            f"new_events={discovery['new_event_count']} "
            f"high_impact_ready={discovery['final_high_impact_ready_count']}"
        )
        remote_chain = run_remote_authority_chain(STATE_DIR)
        print(
            "[X/meta-remote-authority] "
            f"declarations={remote_chain['declaration_count']} "
            f"promoted={remote_chain['promoted_count']} "
            f"candidates={remote_chain['candidate_count']}"
        )
    except Exception as e:
        print(f"[X/discovery-closed-loop] error (continuing): {e}")
    try:
        write_x_status(stats, meta_cycle_ok=True)
        self_recover(stats)
        mutual_recovery_cycle(stats)
    except Exception as e:
        print(f"[X] recovery error (continuing): {e}")


def _run_self_dev(focus: str = ""):
    try:
        from engine.self_dev import run_self_dev_cycle
        from engine.model_client import get_client
        client = get_client()
        result = run_self_dev_cycle(client, focus=focus)
        print(f"[X/self-dev] {result.get('status')} | {result.get('description', '')}")
        return result
    except Exception as e:
        print(f"[X/self-dev] error (continuing): {e}")
        return {}


def _analyze_failures(results: dict, stats: dict) -> str:
    failing = [tid for tid, v in results.items() if v != "PASS"]
    if not failing:
        return ""
    domains = {}
    for tid in failing:
        task_file = TASKS_DIR / f"{tid}.json"
        try:
            import json as _j
            task = _j.loads(task_file.read_text())
            d = task.get("domain", "general")
            domains[d] = domains.get(d, 0) + 1
        except Exception:
            pass
    if domains:
        top = max(domains, key=domains.get)
        return f"improve performance on {top} domain tasks"
    return "improve error handling and retry logic"


def mode_full(new_task_count: int = DEFAULT_NEW_TASKS, max_iter: int | None = None):
    print("[X] === FULL AUTONOMOUS CYCLE ===")
    stats = kb.get_stats()
    workers = _adaptive_workers(stats)
    effective_max_iter = max_iter or _adaptive_max_iter(stats)

    _run_meta_and_recovery(stats)

    print(f"[X] generating {new_task_count} new tasks...")
    try:
        new_tasks = generate_new_tasks(new_task_count)
        push_new_tasks(new_tasks)
    except Exception as e:
        print(f"[X] task generation failed (continuing): {e}")

    pending = discover_pending_tasks(max_tasks=50)
    results = {}
    if not pending:
        print("[X] no pending tasks")
    else:
        results = run_parallel(pending, effective_max_iter, workers)
        passed = sum(1 for v in results.values() if v == "PASS")
        print(f"[X] cycle complete: {passed}/{len(results)} passed")

    stats = kb.get_stats()
    push_knowledge_summary(stats)

    focus = _analyze_failures(results, stats)
    _run_self_dev(focus)

    try:
        write_x_status(stats, meta_cycle_ok=True)
        self_recover(stats)
        mutual_recovery_cycle(stats)
    except Exception as e:
        print(f"[X] post-run recovery error (continuing): {e}")


def mode_run(task_ids: list[str] | None, max_iter: int = DEFAULT_MAX_ITER):
    stats = kb.get_stats()
    if not task_ids:
        task_ids = discover_pending_tasks()
    if not task_ids:
        print("[X] nothing to run")
        return
    workers = _adaptive_workers(stats)
    results = run_parallel(task_ids, max_iter, workers)
    push_knowledge_summary(kb.get_stats())
    write_x_status(kb.get_stats(), meta_cycle_ok=True)
    for tid, status in results.items():
        print(f"  {tid}: {status}")


def mode_expand(count: int = DEFAULT_NEW_TASKS):
    tasks = generate_new_tasks(count)
    push_new_tasks(tasks)


def mode_report():
    stats = kb.get_stats()
    push_knowledge_summary(stats)
    write_x_status(stats, meta_cycle_ok=True)
    mutual_recovery_cycle(stats)


def mode_selfdev(focus: str = ""):
    print("[X] === SELF-DEVELOPMENT CYCLE ===")
    result = _run_self_dev(focus)
    print(f"[X] self-dev result: {result}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "full":
        new_count = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_NEW_TASKS
        max_iter = int(sys.argv[3]) if len(sys.argv) > 3 else None
        mode_full(new_count, max_iter)
    elif mode == "run":
        task_ids = sys.argv[2:] if len(sys.argv) > 2 else None
        mode_run(task_ids)
    elif mode == "expand":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_NEW_TASKS
        mode_expand(count)
    elif mode == "report":
        mode_report()
    elif mode == "selfdev":
        focus = sys.argv[2] if len(sys.argv) > 2 else ""
        mode_selfdev(focus)
    else:
        print(f"Unknown mode: {mode}. Use: full | run | expand | report | selfdev")
        sys.exit(1)
