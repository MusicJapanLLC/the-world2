"""X Recovery Engine — self-recovery + mutual recovery with Senju/META."""

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SENJU_INBOX = ROOT / "senju" / "inbox" / "codegen_events.ndjson"
SENJU_KNOWLEDGE = ROOT / "senju" / "knowledge" / "codegen_patterns.ndjson"
SENJU_STATUS = ROOT / "senju" / "status" / "codegen_status.json"
SENJU_X_CHANNEL = ROOT / "senju" / "inbox" / "x_recovery.ndjson"
X_STATUS = ROOT / "automation" / "codegen" / "meta_state" / "x_status.json"
X_ATTACK_LOG = ROOT / "automation" / "codegen" / "meta_state" / "attack_research.ndjson"


def _append(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_x_status(stats: dict, meta_cycle_ok: bool, last_error: str = ""):
    total = len(stats)
    passing = sum(1 for v in stats.values() if v.get("successes", 0) > 0)
    X_STATUS.parent.mkdir(parents=True, exist_ok=True)
    X_STATUS.write_text(json.dumps({
        "system": "X",
        "ts": _ts(),
        "epoch": int(time.time()),
        "total_tasks": total,
        "passing": passing,
        "success_rate": round(passing / max(total, 1), 3),
        "meta_cycle_ok": meta_cycle_ok,
        "last_error": last_error,
        "needs_help": passing == 0 and total > 0,
    }, indent=2, ensure_ascii=False))


def read_x_status() -> dict:
    if not X_STATUS.exists():
        return {}
    try:
        return json.loads(X_STATUS.read_text())
    except Exception:
        return {}


def read_senju_status() -> dict:
    if not SENJU_STATUS.exists():
        return {}
    try:
        return json.loads(SENJU_STATUS.read_text())
    except Exception:
        return {}


def offer_help_to_senju(reason: str, payload: dict):
    _append(SENJU_X_CHANNEL, {"from": "X", "to": "Senju", "event": "offer_help",
                               "ts": _ts(), "reason": reason, "payload": payload})
    print(f"[X/recovery] offered help to Senju: {reason}")


def request_help_from_senju(reason: str):
    _append(SENJU_INBOX, {"source": "X", "event": "request_help",
                           "ts": _ts(), "reason": reason, "x_status": read_x_status()})
    print(f"[X/recovery] requested help from Senju: {reason}")


def mutual_recovery_cycle(stats: dict):
    senju = read_senju_status()
    x_passing = sum(1 for v in stats.values() if v.get("successes", 0) > 0)
    x_total = len(stats)
    senju_rate = senju.get("success_rate", 1.0)
    x_rate = round(x_passing / max(x_total, 1), 3)
    print(f"[X/recovery] X={x_rate:.1%} Senju={senju_rate:.1%}")
    if x_rate < 0.2 and x_total > 0:
        request_help_from_senju(f"X success rate critically low: {x_rate:.1%} ({x_passing}/{x_total})")
    if senju_rate < 0.2 and x_rate > 0.5:
        try:
            from . import knowledge_base as kb
            patterns = kb.get_successful_patterns(limit=10)
            offer_help_to_senju(
                f"Senju rate low ({senju_rate:.1%}), sharing X patterns",
                {"patterns": [{"task": p.get("task_name"), "domain": p.get("domain"),
                               "code": p.get("code", "")[:300]} for p in patterns[:5]]},
            )
        except Exception as e:
            print(f"[X/recovery] knowledge share error: {e}")
    return {"x_rate": x_rate, "senju_rate": senju_rate}


def log_attack_research(cve_id: str, description: str, test_result: str,
                        bypass_attempted: bool, bypass_succeeded: bool,
                        code_generated: str = ""):
    record = {
        "ts": _ts(), "cve_id": cve_id, "description": description[:300],
        "bypass_attempted": bypass_attempted, "bypass_succeeded": bypass_succeeded,
        "test_result": test_result[:200], "code_snippet": code_generated[:500],
    }
    _append(X_ATTACK_LOG, record)
    if bypass_succeeded:
        _append(SENJU_KNOWLEDGE, {**record, "source": "X_attack_research",
                                   "event": "security_pattern", "task_name": f"defense_{cve_id}",
                                   "domain": "security", "code": code_generated})
        print(f"[X/attack] shared defense pattern for {cve_id} to Senju")
    else:
        _append(SENJU_INBOX, {"source": "X", "event": "attack_research_fail",
                               "ts": _ts(), "cve_id": cve_id, "test_result": test_result[:200]})


def run_cve_defense_experiments(intel: dict, client) -> list[dict]:
    from .model_client import strip_fences
    from .meta_v2 import update_hypothesis, load_hypotheses
    results = []
    nvd = intel.get("sources", {}).get("nvd", {})
    for cve in nvd.get("recent", []):
        if cve.get("severity") not in ("HIGH", "CRITICAL"):
            continue
        cve_id = cve["id"]
        desc = cve.get("desc", "")
        print(f"[X/attack] experimenting on {cve_id} ({cve['severity']})")
        prompt = (
            f"Write Python defensive code that detects or prevents the attack pattern "
            f"described in {cve_id}.\n\nVulnerability: {desc}\n\n"
            f"Write ONLY raw Python. Include test_defense() returning True if defense works."
        )
        try:
            code = strip_fences(client.complete(prompt, max_tokens=2048))
            compile(code, "<cve_defense>", "exec")
            succeeded, test_result = True, "compiled OK"
        except Exception as e:
            code, succeeded, test_result = "", False, str(e)[:200]
        log_attack_research(cve_id, desc, test_result, True, succeeded, code)
        for h in load_hypotheses():
            if cve_id in h.get("claim", ""):
                update_hypothesis(h["id"], succeeded, test_result)
                break
        results.append({"cve_id": cve_id, "succeeded": succeeded})
    return results


def self_recover(stats: dict) -> list[str]:
    try:
        from .meta_v2 import inject_work_item
    except Exception:
        return []
    queue_file = ROOT / "senju" / "queue" / "work_items.json"
    stalled = [tid for tid, v in stats.items()
               if v.get("attempts", 0) >= 5 and v.get("successes", 0) == 0]
    for tid in stalled[:3]:
        inject_work_item(queue_file, {"type": "codegen_task_recovery", "name": tid,
                                      "task_id": tid, "source": "X_self_recovery",
                                      "recovery": True}, priority=0)
        print(f"[X/recovery] re-injected stalled task: {tid}")
    if stalled:
        _append(SENJU_INBOX, {"source": "X", "event": "self_recovery", "ts": _ts(),
                               "stalled_tasks": stalled[:3], "action": "re-injected at priority 0"})
    return stalled[:3]
