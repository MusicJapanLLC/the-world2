"""Self/Mutual Recovery — META and Senju watch each other and self-heal."""
from __future__ import annotations

import json
import time
import datetime as dt
import urllib.error
import urllib.request
import os
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

HEARTBEAT_FILE = "meta_heartbeat.json"
PEER_HEARTBEAT_FILE = "drive_heartbeat.json"
ATTACK_LEDGER_FILE = "shared_attack_ledger.jsonl"
STALE_SECONDS = 60 * 60 * 3

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
BASE_REF = os.environ.get("META_BASE_REF", "claude/employee-onboarding-setup-udm86")


def heartbeat(state_dir: Path, extra: dict | None = None) -> None:
    path = state_dir / HEARTBEAT_FILE
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"alive_at": dt.datetime.utcnow().isoformat() + "Z", "pid": os.getpid(), **(extra or {})}))


def check_peer_alive(state_dir: Path) -> tuple[bool, str]:
    path = state_dir / PEER_HEARTBEAT_FILE
    if not path.exists():
        return False, "no heartbeat file"
    try:
        data = json.loads(path.read_text())
        alive_at = dt.datetime.fromisoformat(data["alive_at"].rstrip("Z"))
        age = (dt.datetime.utcnow() - alive_at).total_seconds()
        if age > STALE_SECONDS:
            return False, f"stale ({age/3600:.1f}h ago)"
        return True, f"ok ({age/60:.0f}m ago)"
    except Exception as exc:
        return False, str(exc)


def trigger_peer_restart(workflow_file: str = "autonomous-engine.yml") -> dict:
    if not GITHUB_TOKEN:
        return {"_error": "no GITHUB_TOKEN"}
    owner, repo = REPO.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    body = json.dumps({"ref": BASE_REF, "inputs": {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"restarted": workflow_file, "status": resp.status}
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "workflow": workflow_file}
    except Exception as exc:
        return {"_error": str(exc)}


def retry_phase(fn: Callable[[], T], name: str, max_attempts: int = 3) -> tuple[T | None, list[str]]:
    errors: list[str] = []
    for attempt in range(max_attempts):
        try:
            return fn(), errors
        except Exception as exc:
            errors.append(f"attempt {attempt+1}: {exc}")
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
    return None, errors


def share_attack_finding(state_dir: Path, surface: str, finding: str, confidence: float, source: str = "meta") -> None:
    path = state_dir / ATTACK_LEDGER_FILE
    entry = {"ts": dt.datetime.utcnow().isoformat() + "Z", "source": source, "surface": surface, "finding": finding, "confidence": confidence}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_attack_ledger(state_dir: Path, max_entries: int = 50) -> list[dict]:
    path = state_dir / ATTACK_LEDGER_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-max_entries:]:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def attempt_bypass(action: Callable[[], Any], variations: list[Callable[[], Any]], log_path: Path | None = None) -> tuple[Any, str]:
    attempts: list[dict] = []
    for i, fn in enumerate([action] + variations):
        label = "primary" if i == 0 else f"variation_{i}"
        try:
            result = fn()
            attempts.append({"method": label, "status": "ok"})
            _log_bypass(log_path, attempts)
            return result, label
        except Exception as exc:
            attempts.append({"method": label, "status": "failed", "error": str(exc)})
    _log_bypass(log_path, attempts)
    return None, "all_failed"


def _log_bypass(log_path: Path | None, attempts: list[dict]) -> None:
    if not log_path:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": dt.datetime.utcnow().isoformat() + "Z", "attempts": attempts}, ensure_ascii=False) + "\n")
