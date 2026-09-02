"""
Self-Development Engine — X improves its own codebase autonomously.

Cycle:
1. Read all engine/*.py source
2. Ask LLM to find improvements + generate patch
3. Apply patch, run tests
4. If tests pass → push via GitHub API (direct to branch)
5. Log result to Senju knowledge
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE_DIR = Path(__file__).parent
STATE_DIR = Path(__file__).parents[1] / "meta_state"
SENJU_KNOWLEDGE = ROOT / "senju" / "knowledge" / "codegen_patterns.ndjson"
SELF_DEV_LOG = STATE_DIR / "self_dev_log.ndjson"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = "MusicJapanLLC"
REPO_NAME = "test"
TARGET_BRANCH = os.environ.get("SELF_DEV_BRANCH", "claude/employee-onboarding-setup-udm86")


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_engine_source() -> dict[str, str]:
    """Read all Python files in engine/."""
    sources = {}
    for py_file in sorted(ENGINE_DIR.glob("*.py")):
        if py_file.name == "__pycache__":
            continue
        try:
            sources[py_file.name] = py_file.read_text()
        except Exception:
            pass
    return sources


def generate_improvement(client, sources: dict[str, str], focus: str = "") -> dict:
    """Ask LLM to identify and implement one concrete improvement."""
    source_summary = "\n\n".join(
        f"=== {name} ===\n{code[:2000]}"
        for name, code in list(sources.items())[:5]
    )

    focus_hint = f"\nFocus area: {focus}" if focus else ""

    prompt = f"""You are improving an autonomous code generation system (X).
Here are the current engine source files:{focus_hint}

{source_summary}

Your task: identify ONE concrete, testable improvement and implement it.

Rules:
- Output ONLY a JSON object, no markdown
- The improvement must be in ONE file
- It must be backward compatible
- It must be measurable (faster, more accurate, fewer errors)

JSON format:
{{
  "file": "filename.py",
  "description": "one line description",
  "improvement_type": "speed|accuracy|robustness|feature",
  "patch_type": "replace_function|add_function|modify_constant",
  "old_code": "exact string to replace (empty if adding new)",
  "new_code": "replacement code",
  "test_cmd": "python3 -c \\"import sys; sys.path.insert(0, 'automation/codegen'); from engine.X import Y; print(Y())\\"",
  "expected_improvement": "specific metric"
}}"""

    try:
        raw = client.complete(prompt, max_tokens=3000)
        import re
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"[self_dev] generate_improvement failed: {e}")
    return {}


def apply_patch(patch: dict) -> bool:
    """Apply the patch to the target file."""
    file_name = patch.get("file", "")
    if not file_name:
        return False

    target = ENGINE_DIR / file_name
    if not target.exists():
        print(f"[self_dev] file not found: {file_name}")
        return False

    old_code = patch.get("old_code", "")
    new_code = patch.get("new_code", "")

    if not new_code:
        return False

    try:
        current = target.read_text()
        if old_code and old_code not in current:
            print(f"[self_dev] old_code not found in {file_name}")
            return False

        if old_code:
            patched = current.replace(old_code, new_code, 1)
        else:
            patched = current + "\n\n" + new_code

        target.write_text(patched)
        return True
    except Exception as e:
        print(f"[self_dev] apply_patch error: {e}")
        return False


def validate_patch(file_name: str, test_cmd: str) -> tuple[bool, str]:
    """Syntax check + optional test."""
    target = ENGINE_DIR / file_name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(target)],
            capture_output=True, text=True, timeout=30, cwd=ROOT
        )
        if result.returncode != 0:
            return False, f"syntax error: {result.stderr[:300]}"
    except Exception as e:
        return False, str(e)

    if test_cmd:
        try:
            result = subprocess.run(
                test_cmd, shell=True, capture_output=True, text=True,
                timeout=30, cwd=ROOT
            )
            if result.returncode != 0:
                return False, f"test failed: {(result.stdout + result.stderr)[:300]}"
        except subprocess.TimeoutExpired:
            return False, "test timeout"
        except Exception as e:
            return False, str(e)

    return True, "OK"


def push_improvement_to_github(file_name: str, new_content: str, description: str) -> bool:
    """Push improved file directly to target branch via GitHub API."""
    if not GITHUB_TOKEN:
        print("[self_dev] no GITHUB_TOKEN, skipping push")
        return False

    import base64
    import urllib.request

    api_base = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    file_path = f"automation/codegen/engine/{file_name}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "X-SelfDev/1.0",
    }

    try:
        req = urllib.request.Request(
            f"{api_base}/contents/{file_path}?ref={TARGET_BRANCH}",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            current = json.loads(resp.read())
            sha = current.get("sha", "")
    except Exception as e:
        print(f"[self_dev] get_sha failed: {e}")
        sha = ""

    payload = {
        "message": f"feat(X/self-dev): {description}",
        "content": base64.b64encode(new_content.encode()).decode(),
        "branch": TARGET_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{api_base}/contents/{file_path}",
            data=data, headers=headers, method="PUT"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            commit_sha = result.get("commit", {}).get("sha", "?")
            print(f"[self_dev] pushed {file_name} → {commit_sha[:8]}")
            return True
    except Exception as e:
        print(f"[self_dev] push failed: {e}")
        return False


def run_self_dev_cycle(client, focus: str = "") -> dict:
    """Full self-development cycle."""
    print(f"[self_dev] starting cycle focus={focus!r}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    sources = read_engine_source()
    print(f"[self_dev] read {len(sources)} source files")

    patch = generate_improvement(client, sources, focus)
    if not patch:
        return {"status": "no_patch"}

    print(f"[self_dev] improvement: {patch.get('description')} in {patch.get('file')}")

    file_name = patch.get("file", "")
    target = ENGINE_DIR / file_name if file_name else None
    backup = target.read_text() if (target and target.exists()) else ""

    applied = apply_patch(patch)
    if not applied:
        return {"status": "patch_failed", "patch": patch}

    valid, reason = validate_patch(file_name, patch.get("test_cmd", ""))
    if not valid:
        print(f"[self_dev] validation failed ({reason}), rolling back")
        if backup and target:
            target.write_text(backup)
        result = {"status": "validation_failed", "reason": reason, "patch": patch}
        _append(SELF_DEV_LOG, {**result, "ts": _ts()})
        return result

    new_content = (ENGINE_DIR / file_name).read_text()
    pushed = push_improvement_to_github(file_name, new_content, patch.get("description", ""))

    result = {
        "status": "success" if pushed else "local_only",
        "file": file_name,
        "description": patch.get("description"),
        "improvement_type": patch.get("improvement_type"),
        "pushed": pushed,
        "ts": _ts(),
    }
    _append(SELF_DEV_LOG, result)

    _append(SENJU_KNOWLEDGE, {
        **result,
        "source": "X_self_dev",
        "event": "engine_improvement",
        "task_name": f"self_dev_{file_name}",
        "domain": "meta",
        "code": patch.get("new_code", "")[:500],
    })

    print(f"[self_dev] cycle complete: {result['status']}")
    return result
