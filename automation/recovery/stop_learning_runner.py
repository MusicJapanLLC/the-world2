"""Read real GitHub Actions outcomes and persist production stop-learning state."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from recovery_tuner import derive_recovery_tuning
from stop_learning import update_learning_state

HERE = Path(__file__).resolve().parent
CONTROL_FILE = HERE / "runtime_control_state.json"
REGISTRY_FILE = HERE / "approved_persistence_registry.json"
STATE_LABEL = "meta-stop-learning-state"
STATE_TITLE = "[THE-WORLD] Production Stop Learning State"
WORKFLOWS = (
    "meta-consciousness.yml",
    "autonomous-codegen.yml",
    "autonomous-engine.yml",
    "meta-four-pillar-production-loop.yml",
    "owned-self-recovery-worker.yml",
    "meta-production-stop-learning.yml",
)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _call(method: str, url: str, token: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 422}:
            return {"_http": exc.code}
        raise


def _parse_time(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _observation(run: dict) -> dict | None:
    conclusion = run.get("conclusion")
    if conclusion not in {"success", "failure", "cancelled", "timed_out"}:
        return None
    started = _parse_time(run.get("run_started_at") or run.get("created_at"))
    updated = _parse_time(run.get("updated_at"))
    duration = None
    if started and updated:
        duration = max(0.0, (updated - started).total_seconds() / 60.0)
    mapped = "failure" if conclusion == "timed_out" else conclusion
    return {
        "run_id": run.get("id"),
        "workflow": run.get("name"),
        "conclusion": mapped,
        "stable_minutes": duration or 30.0,
        "mttr_minutes": duration,
        "created_at": run.get("created_at"),
    }


def _load_previous(repo: str, token: str) -> tuple[dict, int | None]:
    owner, name = repo.split("/", 1)
    query = urllib.parse.urlencode({"state": "open", "labels": STATE_LABEL, "per_page": "100"})
    rows = _call("GET", f"https://api.github.com/repos/{owner}/{name}/issues?{query}", token)
    if not isinstance(rows, list):
        return {}, None
    target = next((row for row in rows if row.get("title") == STATE_TITLE and "pull_request" not in row), None)
    if not target:
        return {}, None
    try:
        body = json.loads(target.get("body") or "{}")
    except json.JSONDecodeError:
        body = {}
    return body, int(target["number"])


def _recent_observations(repo: str, token: str, seen: set[int]) -> list[dict]:
    owner, name = repo.split("/", 1)
    out: list[dict] = []
    for workflow in WORKFLOWS:
        encoded = urllib.parse.quote(workflow, safe="")
        url = f"https://api.github.com/repos/{owner}/{name}/actions/workflows/{encoded}/runs?per_page=20"
        doc = _call("GET", url, token)
        runs = doc.get("workflow_runs", []) if isinstance(doc, dict) else []
        for run in runs:
            run_id = run.get("id")
            if not isinstance(run_id, int) or run_id in seen:
                continue
            item = _observation(run)
            if item:
                out.append(item)
    out.sort(key=lambda row: str(row.get("created_at") or ""))
    return out


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN required")
    previous, issue_number = _load_previous(repo, token)
    seen = {int(x) for x in previous.get("seen_run_ids", []) if isinstance(x, int) or str(x).isdigit()}
    observations = _recent_observations(repo, token, seen)
    controls = _load(CONTROL_FILE, {})
    registry = _load(REGISTRY_FILE, {})
    state = update_learning_state(previous, observations, controls)
    state["recovery_tuning"] = derive_recovery_tuning(state, registry, controls)
    state["seen_run_ids"] = list((seen | {int(row["run_id"]) for row in observations if row.get("run_id")}))[-500:]
    state["observations_processed"] = len(observations)
    state["workflows"] = list(WORKFLOWS)

    owner, name = repo.split("/", 1)
    base = f"https://api.github.com/repos/{owner}/{name}"
    _call("POST", f"{base}/labels", token, {
        "name": STATE_LABEL,
        "description": "Production stop-learning state for META/X/Senju",
    })
    body = json.dumps(state, ensure_ascii=False, indent=2)
    if issue_number is None:
        created = _call("POST", f"{base}/issues", token, {
            "title": STATE_TITLE,
            "body": body,
            "labels": [STATE_LABEL],
        })
        print(f"created stop-learning state issue #{created.get('number')}")
    else:
        _call("PATCH", f"{base}/issues/{issue_number}", token, {"body": body})
        print(f"updated stop-learning state issue #{issue_number}")

    Path("/tmp/stop-learning-state.json").write_text(body + "\n", encoding="utf-8")
    print(json.dumps({
        "processed": len(observations),
        "failure_score": state["failure_score"],
        "reward_score": state["reward_score"],
        "active_controls": state["active_controls"],
        "pending_failures": list(state.get("pending_failures", {})),
        "recovery_tuning": state["recovery_tuning"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
