"""META v2 — 6-capability autonomous engine (X system).

1. COMMAND CHANNEL    : drive_engine attack parameter rewrite
2. QUEUE SURGERY      : Senju queue priority manipulation + WorkItem injection
3. EXTERNAL INTEL     : NVD/CVE + GitHub Advisory fetch every cycle
4. AGENT DISPATCH     : workflow_dispatch to Jules and other AIs
5. HYPOTHESIS TRACK   : hypothesis → experiment → result → confidence update
6. SELF-REWRITE       : propose improvements to own code as PRs
+ RECOVERY            : self-recovery + mutual recovery with Senju
"""

import base64
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = ROOT / "automation" / "codegen" / "meta_state"
HYPOTHESIS_FILE = STATE_DIR / "hypotheses.json"
INTEL_FILE = STATE_DIR / "external_intel.json"
COMMAND_LOG = STATE_DIR / "command_log.ndjson"
HEARTBEAT_FILE = STATE_DIR / "last_cycle.json"


def _ensure():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def rewrite_attack_params(target_file: Path, updates: dict) -> bool:
    _ensure()
    if not target_file.exists():
        target_file.parent.mkdir(parents=True, exist_ok=True)
        current = {}
    else:
        try:
            current = json.loads(target_file.read_text())
        except Exception:
            current = {}
    current.update(updates)
    current["_meta_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    current["_meta_source"] = "meta_v2_command_channel"
    target_file.write_text(json.dumps(current, indent=2, ensure_ascii=False))
    _log("command_channel", {"target": str(target_file), "updates": updates})
    print(f"[meta/cmd] rewrote {target_file.name}: {list(updates.keys())}")
    return True


def push_drive_engine_params(params: dict):
    targets = [
        ROOT / "senju" / "state" / "strategy.json",
        ROOT / "automation" / "control_plane" / "value_policy.json",
    ]
    for t in targets:
        rewrite_attack_params(t, params)


def inject_work_item(queue_file: Path, item: dict, priority: int = 0):
    _ensure()
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue = []
    if queue_file.exists():
        try:
            queue = json.loads(queue_file.read_text())
        except Exception:
            queue = []
    item["_injected_by"] = "meta_v2"
    item["_injected_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    queue.insert(min(priority, len(queue)), item)
    queue_file.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
    _log("queue_surgery", {"queue": str(queue_file), "item": item, "priority": priority})
    print(f"[meta/queue] injected '{item.get('name','?')}' at priority {priority}")
    return queue


def reprioritize_queue(queue_file: Path, key: str, boost_fn=None):
    if not queue_file.exists():
        return []
    queue = json.loads(queue_file.read_text())
    if boost_fn:
        queue.sort(key=boost_fn, reverse=True)
    else:
        queue.sort(key=lambda x: x.get(key, 0), reverse=True)
    queue_file.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
    print(f"[meta/queue] reprioritized {len(queue)} items by '{key}'")
    return queue


def inject_codegen_tasks_to_senju():
    queue_file = ROOT / "senju" / "queue" / "work_items.json"
    try:
        from .knowledge_base import get_stats
        stats = get_stats()
        pending = [tid for tid, v in stats.items() if v.get("successes", 0) == 0]
        for tid in pending[:5]:
            inject_work_item(queue_file, {"type": "codegen_task", "name": tid,
                                          "task_id": tid, "source": "meta_v2_queue_surgery"}, priority=0)
    except Exception as e:
        print(f"[meta/queue] stats unavailable: {e}")


def _fetch_json(url: str, timeout: int = 10) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "codegen-meta-v2/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[meta/intel] fetch failed {url}: {e}")
        return None


def fetch_external_intel(keywords: list[str] | None = None) -> dict:
    _ensure()
    keywords = keywords or ["python", "injection", "rce", "authentication"]
    intel: dict[str, Any] = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {},
    }
    nvd = _fetch_json("https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=5&startIndex=0")
    if nvd:
        intel["sources"]["nvd"] = {
            "total": nvd.get("totalResults", 0),
            "recent": [
                {"id": c["cve"]["id"],
                 "desc": c["cve"].get("descriptions", [{}])[0].get("value", "")[:200],
                 "severity": c["cve"].get("metrics", {}).get("cvssMetricV31", [{}])[0]
                             .get("cvssData", {}).get("baseSeverity", "UNKNOWN")}
                for c in nvd.get("vulnerabilities", [])[:5]
            ],
        }
    gh_advisory = _fetch_json("https://api.github.com/advisories?per_page=5&type=reviewed")
    if gh_advisory and isinstance(gh_advisory, list):
        intel["sources"]["github_advisory"] = [
            {"id": a.get("ghsa_id"), "summary": a.get("summary", "")[:200],
             "severity": a.get("severity"), "cve": a.get("cve_id")}
            for a in gh_advisory[:5]
        ]
    INTEL_FILE.write_text(json.dumps(intel, indent=2, ensure_ascii=False))
    _log("external_intel", {"sources": list(intel["sources"].keys())})
    print(f"[meta/intel] fetched from: {list(intel['sources'].keys())}")
    return intel


def dispatch_to_agent(workflow_file: str, ref: str, inputs: dict) -> bool:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
    if not token:
        print("[meta/dispatch] no GITHUB_TOKEN, skipping")
        return False
    owner, repo_name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo_name}/actions/workflows/{workflow_file}/dispatches"
    payload = json.dumps({"ref": ref, "inputs": inputs}).encode()
    try:
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            status = r.status
        _log("agent_dispatch", {"workflow": workflow_file, "inputs": inputs, "status": status})
        print(f"[meta/dispatch] {workflow_file} → {status}")
        return status in (200, 204)
    except Exception as e:
        print(f"[meta/dispatch] failed: {e}")
        _log("agent_dispatch", {"workflow": workflow_file, "error": str(e)})
        return False


def dispatch_codegen_expand(count: int = 10):
    return dispatch_to_agent(
        "codegen-task-expander.yml",
        ref=os.environ.get("GITHUB_REF_NAME", "claude/autonomous-code-generation-github-kje2uj"),
        inputs={"count": str(count)},
    )


def dispatch_senju_cycle():
    for wf in ["senju-trusted-owner-scope.yml", "standment-autonomous-rnd.yml"]:
        dispatch_to_agent(wf, ref="main", inputs={})


def load_hypotheses() -> list[dict]:
    _ensure()
    if not HYPOTHESIS_FILE.exists():
        return []
    return json.loads(HYPOTHESIS_FILE.read_text())


def save_hypotheses(hypotheses: list[dict]):
    _ensure()
    HYPOTHESIS_FILE.write_text(json.dumps(hypotheses, indent=2, ensure_ascii=False))


def add_hypothesis(claim: str, domain: str, experiment: str) -> dict:
    hypotheses = load_hypotheses()
    h = {
        "id": f"H{len(hypotheses)+1:04d}",
        "claim": claim, "domain": domain, "experiment": experiment,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "confidence": 0.5, "trials": 0, "successes": 0,
        "status": "pending", "evidence": [],
    }
    hypotheses.append(h)
    save_hypotheses(hypotheses)
    _log("hypothesis", {"action": "add", "id": h["id"], "claim": claim})
    print(f"[meta/hypo] added {h['id']}: {claim[:60]}")
    return h


def update_hypothesis(h_id: str, passed: bool, evidence: str = ""):
    hypotheses = load_hypotheses()
    for h in hypotheses:
        if h["id"] == h_id:
            h["trials"] += 1
            if passed:
                h["successes"] += 1
            h["confidence"] = round((h["successes"] + 1) / (h["trials"] + 2), 3)
            h["status"] = ("confirmed" if h["confidence"] > 0.8 else
                           "refuted" if h["confidence"] < 0.2 else "pending")
            if evidence:
                h["evidence"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       "passed": passed, "note": evidence[:200]})
            _log("hypothesis", {"action": "update", "id": h_id,
                                "confidence": h["confidence"], "status": h["status"]})
            print(f"[meta/hypo] {h_id} confidence={h['confidence']} status={h['status']}")
            break
    save_hypotheses(hypotheses)


def auto_hypothesize_from_intel(intel: dict) -> list[dict]:
    new_hypotheses = []
    nvd = intel.get("sources", {}).get("nvd", {})
    for cve in nvd.get("recent", []):
        if cve.get("severity") in ("HIGH", "CRITICAL"):
            h = add_hypothesis(
                claim=f"Generating defensive code against {cve['id']} improves test pass rate",
                domain="security",
                experiment=f"Generate code that handles {cve['id']} scenario and run tests",
            )
            new_hypotheses.append(h)
    return new_hypotheses


def propose_self_improvement(current_file: Path, improvement_note: str, client) -> str:
    from .model_client import strip_fences
    if not current_file.exists():
        return ""
    current_code = current_file.read_text()
    prompt = (
        f"You are improving an autonomous AI engine file.\n\n"
        f"# Improvement goal\n{improvement_note}\n\n"
        f"# Current code\n```python\n{current_code[:6000]}\n```\n\n"
        f"Rewrite the file with the improvement applied. Output ONLY raw Python."
    )
    improved = strip_fences(client.complete(prompt, max_tokens=8192))
    staging_path = current_file.parent / f"{current_file.stem}_improved.py"
    staging_path.write_text(improved)
    _log("self_rewrite", {"target": str(current_file), "staging": str(staging_path)})
    print(f"[meta/rewrite] improved version written to {staging_path.name}")
    return str(staging_path)


def auto_pr_self_improvement(staging_path: str, improvement_note: str) -> bool:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
    if not token or not staging_path:
        return False
    staging = Path(staging_path)
    if not staging.exists():
        return False
    owner, repo_name = repo.split("/", 1)
    branch = f"meta/self-improve-{time.strftime('%Y%m%d-%H%M%S')}"
    encoded = base64.b64encode(staging.read_text().encode()).decode()
    rel_path = str(staging.relative_to(ROOT))

    def _api(method: str, path: str, body: dict | None = None):
        url = f"https://api.github.com/repos/{owner}/{repo_name}/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    try:
        sha = _api("GET", "git/ref/heads/claude/autonomous-code-generation-github-kje2uj")["object"]["sha"]
        _api("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
        try:
            file_sha = _api("GET", f"contents/{rel_path}?ref={branch}").get("sha", "")
        except Exception:
            file_sha = ""
        body: dict = {"message": f"meta(self-rewrite): {improvement_note[:60]}",
                      "content": encoded, "branch": branch}
        if file_sha:
            body["sha"] = file_sha
        _api("PUT", f"contents/{rel_path}", body)
        _api("POST", "pulls", {
            "title": f"[META] Self-improvement: {improvement_note[:60]}",
            "body": f"Auto-generated by META v2 self-rewrite capability.\n\n{improvement_note}",
            "head": branch, "base": "claude/autonomous-code-generation-github-kje2uj",
        })
        print(f"[meta/rewrite] PR created: {branch}")
        _log("self_rewrite_pr", {"branch": branch, "path": rel_path})
        return True
    except Exception as e:
        print(f"[meta/rewrite] PR creation failed: {e}")
        return False


def write_heartbeat():
    _ensure()
    HEARTBEAT_FILE.write_text(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch": int(time.time()),
    }))


def check_heartbeat(max_gap_hours: float = 10.0) -> bool:
    if not HEARTBEAT_FILE.exists():
        return False
    try:
        data = json.loads(HEARTBEAT_FILE.read_text())
        gap = time.time() - data["epoch"]
        alive = gap < max_gap_hours * 3600
        if not alive:
            print(f"[meta/heartbeat] DEAD — last cycle {gap/3600:.1f}h ago")
            _log("heartbeat", {"status": "dead", "gap_hours": round(gap / 3600, 2)})
        return alive
    except Exception:
        return False


def run_full_meta_cycle(client=None):
    print("[meta] === META v2 FULL CYCLE (X) ===")
    intel = fetch_external_intel()
    auto_hypothesize_from_intel(intel)
    nvd_recent = intel.get("sources", {}).get("nvd", {}).get("recent", [])
    if nvd_recent:
        push_drive_engine_params({
            "intel_cve_count": len(nvd_recent),
            "top_severity": nvd_recent[0].get("severity", "UNKNOWN"),
            "last_intel_at": intel["fetched_at"],
        })
    inject_codegen_tasks_to_senju()
    dispatch_codegen_expand(count=5)
    dispatch_senju_cycle()
    try:
        from . import knowledge_base as kb
        from .recovery import (mutual_recovery_cycle, self_recover, write_x_status,
                               run_cve_defense_experiments)
        stats = kb.get_stats()
        write_x_status(stats, meta_cycle_ok=True)
        self_recover(stats)
        mutual_recovery_cycle(stats)
        if client:
            run_cve_defense_experiments(intel, client)
    except Exception as e:
        print(f"[meta] recovery error (continuing): {e}")
    if client:
        improvement_note = "Add cross-agent result aggregation and better error recovery"
        staging = propose_self_improvement(Path(__file__), improvement_note, client)
        if staging:
            auto_pr_self_improvement(staging, improvement_note)
    write_heartbeat()
    print("[meta] === CYCLE COMPLETE ===")


def _log(event_type: str, data: dict):
    _ensure()
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event_type, **data}
    with COMMAND_LOG.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
