"""
Self-Development Engine — X improves its own codebase autonomously.

Cycle:
1. Read engine source plus selected security-boundary source
2. Ask LLM to find one concrete improvement
3. Ordinary engine change: apply + test + push to the configured development branch
4. Security-boundary change: stage proposal only for independent exact-head audit
5. Log result to Senju knowledge
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .security_boundary_proposals import is_security_boundary_target, stage_x_proposal

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


def _boundary_candidate_paths() -> list[Path]:
    """Return representative production control-plane files X may inspect/propose changing."""
    candidates = {
        ROOT / "senju" / "senju" / "safety.py",
        ROOT / "senju" / "senju" / "external.py",
        ROOT / "senju" / "config" / "credential-broker-policy.json",
        ROOT / "senju" / "config" / "authority-self-lease.json",
    }

    # 指定ディレクトリ配下の全ファイルをスキャンして追加
    target_dirs = [
        ROOT / ".github" / "workflows",
        ROOT / "automation" / "control_plane",
        ROOT / "senju" / "labs",
    ]
    for d in target_dirs:
        if d.exists():
            for p in d.rglob("*"):
                if p.is_file():
                    candidates.add(p)

    for pattern in ("AUTHORIZED_TARGETS.md", "authorized_test_targets.json"):
        for path in ROOT.rglob(pattern):
            candidates.add(path)

    return [path for path in sorted(candidates) if path.exists()][:100]


def read_engine_source() -> dict[str, str]:
    """Read X engine files plus selected control-plane files for proposal generation."""
    sources: dict[str, str] = {}

    # 1. 根幹となる engine ディレクトリの Python ファイルを最優先で読み込み
    for py_file in sorted(ENGINE_DIR.glob("*.py")):
        if py_file.name == "__pycache__":
            continue
        try:
            sources[py_file.name] = py_file.read_text(encoding="utf-8")
        except Exception:
            pass

    # 2. バウンダリ対象の管理用ファイルを読み込み
    for path in _boundary_candidate_paths():
        try:
            key = str(path.relative_to(ROOT)).replace("\\", "/")
            sources[key] = path.read_text(encoding="utf-8")
        except Exception:
            pass

    return sources


def generate_improvement(client, sources: dict[str, str], focus: str = "") -> dict:
    """Ask LLM to identify one engine improvement or one audited boundary proposal."""
    
    # Focusキーワードが存在する場合、該当するファイルを優先的にAIへ送るロジック
    items = list(sources.items())
    if focus:
        focus_lower = focus.lower()
        matched = [item for item in items if focus_lower in item[0].lower()]
        others = [item for item in items if focus_lower not in item[0].lower()]
        selected_sources = (matched + others)[:35]
    else:
        selected_sources = items[:35]

    source_summary = "\n\n".join(
        f"=== {name} ===\n{code[:1800]}"
        for name, code in selected_sources
    )

    focus_hint = f"\nFocus area: {focus}" if focus else ""

    prompt = f"""You are improving an autonomous code generation system (X).
Here are current engine and selected production control-plane source files:{focus_hint}

{source_summary}

Your task: identify ONE concrete, testable improvement and implement it.

Rules:
- Output ONLY a JSON object, no markdown
- The improvement must be in ONE provided file
- It must be measurable (faster, more accurate, fewer errors, clearer policy, or stronger reliability)
- For ordinary engine files, changes may be applied after tests
- For safety, external-contact, authorized-target, credential, GitHub workflow, security-workflow, or audit-policy files, generate a proposal normally, but the runtime will stage it for independent security-boundary audit rather than apply it directly
- Never assume that a proposal is already approved

JSON format:
{{
  "file": "exact provided file key",
  "description": "one line description",
  "improvement_type": "speed|accuracy|robustness|feature|policy",
  "patch_type": "replace_function|add_function|modify_constant|replace_text",
  "old_code": "exact string to replace (empty if adding new)",
  "new_code": "replacement code",
  "test_cmd": "optional test command for ordinary engine changes",
  "expected_improvement": "specific metric or policy outcome"
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
    """Apply an ordinary X-engine patch. Security-boundary patches never reach this function."""
    file_name = patch.get("file", "")
    if not file_name or "/" in file_name or "\\" in file_name:
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
        current = target.read_text(encoding="utf-8")
        if old_code and old_code not in current:
            print(f"[self_dev] old_code not found in {file_name}")
            return False

        if old_code:
            patched = current.replace(old_code, new_code, 1)
        else:
            patched = current + "\n\n" + new_code

        target.write_text(patched, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[self_dev] apply_patch error: {e}")
        return False


def validate_patch(file_name: str, test_cmd: str) -> tuple[bool, str]:
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
    """Push ordinary engine improvement directly to configured development branch."""
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


def _stage_boundary_patch(patch: dict) -> dict:
    target_path = str(patch.get("file") or "")
    payload = json.dumps({
        "patch_type": patch.get("patch_type"),
        "old_code": patch.get("old_code", ""),
        "new_code": patch.get("new_code", ""),
        "expected_improvement": patch.get("expected_improvement", ""),
    }, ensure_ascii=False, indent=2)
    return stage_x_proposal(
        target_path=target_path,
        rationale=str(patch.get("description") or "X autonomous security-boundary improvement proposal"),
        proposed_patch=payload,
        evidence={
            "source": "X_self_dev",
            "improvement_type": patch.get("improvement_type"),
            "expected_improvement": patch.get("expected_improvement"),
        },
    )


def run_self_dev_cycle(client, focus: str = "") -> dict:
    """Full self-development cycle with proposal-only handling for control-plane changes."""
    print(f"[self_dev] starting cycle focus={focus!r}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    sources = read_engine_source()
    print(f"[self_dev] read {len(sources)} source files")

    patch = generate_improvement(client, sources, focus)
    if not patch:
        return {"status": "no_patch"}

    print(f"[self_dev] improvement: {patch.get('description')} in {patch.get('file')}")

    file_name = str(patch.get("file") or "")
    if is_security_boundary_target(file_name):
        staged = _stage_boundary_patch(patch)
        result = {
            "status": "boundary_proposal_staged" if staged.get("status") == "requires_independent_audit" else "boundary_proposal_rejected",
            "file": file_name,
            "description": patch.get("description"),
            "improvement_type": patch.get("improvement_type"),
            "proposal": staged,
            "pushed": False,
            "directly_applied": False,
            "ts": _ts(),
        }
        _append(SELF_DEV_LOG, result)
        _append(SENJU_KNOWLEDGE, {
            **result,
            "source": "X_self_dev",
            "event": "security_boundary_change_proposal",
            "task_name": f"boundary_proposal_{staged.get('proposal_id', 'rejected')}",
            "domain": "meta",
        })
        print(f"[self_dev] security-boundary proposal: {result['status']}")
        return result

    target = ENGINE_DIR / file_name if file_name else None
    backup = target.read_text(encoding="utf-8") if (target and target.exists()) else ""

    applied = apply_patch(patch)
    if not applied:
        return {"status": "patch_failed", "patch": patch}

    valid, reason = validate_patch(file_name, patch.get("test_cmd", ""))
    if not valid:
        print(f"[self_dev] validation failed ({reason}), rolling back")
        if backup and target:
            target.write_text(backup, encoding="utf-8")
        result = {"status": "validation_failed", "reason": reason, "patch": patch}
        _append(SELF_DEV_LOG, {**result, "ts": _ts()})
        return result

    new_content = (ENGINE_DIR / file_name).read_text(encoding="utf-8")
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
