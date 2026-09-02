#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

RUNTIME = 'https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-runtime'
MAX_FILES = 16
MAX_FILE_CHARS = 80_000
MAX_TOTAL_CHARS = 220_000
MAX_COMMANDS = 6
MAX_LOG_CHARS = 16_000
ALLOWED_EXECUTABLES = {'node', 'python', 'python3', 'pytest', 'ruff', 'npm', 'npx', 'tsc'}
FORBIDDEN_SHELL = re.compile(r'[;&|><`$]')
SENSITIVE_ENV = re.compile(r'(TOKEN|SECRET|PASSWORD|PRIVATE|CREDENTIAL|API_KEY|ACCESS_KEY|AUTH)', re.I)

INITIAL_SYSTEM = '''You are AI FOUNDRY ENGINEERING COMPILER v2.
Your job is to produce a SMALL, COMPLETE, RUNNABLE software vertical slice from a development request.
Return ONLY strict JSON, no markdown and no commentary.

Exact schema:
{
  "name": "short project name",
  "summary": "what was implemented",
  "files": [{"path": "relative/path", "content": "full UTF-8 file content"}],
  "test_commands": ["one safe local command"],
  "expected_contains": "text expected in index.html or empty string"
}

Rules:
- Prefer dependency-free HTML/CSS/JS for web tasks unless the request clearly requires something else.
- Produce the minimum files needed for a complete vertical slice.
- Include at least one deterministic validation command whenever possible.
- Commands must be direct local commands only: no pipes, redirects, command substitution, chained shell commands, curl, wget, ssh, git push, deploy commands, or secret access.
- File paths must be relative and must not escape the workspace.
- Never claim tests passed; a separate executor verifies them.
'''

REPAIR_SYSTEM = '''You are AI FOUNDRY REPAIR ENGINE v2.
A generated project was executed and failed verification. Fix the project using the failure evidence.
Return ONLY strict JSON, no markdown and no commentary.

Exact schema:
{
  "reason": "brief root cause",
  "replace_files": [{"path": "relative/path", "content": "complete replacement content"}],
  "test_commands": ["safe local validation command"]
}

Rules:
- Make the smallest repair that addresses the observed failure.
- Do not remove useful behavior merely to make a test pass.
- Commands must be direct local commands only: no pipes, redirects, command substitution, chained shell commands, curl, wget, ssh, git push, deploy commands, or secret access.
- Never claim success; the executor reruns verification.
'''


def post_runtime(system_prompt: str, prompt: str) -> str:
    payload = {'action': 'runtime', 'systemPrompt': system_prompt, 'messages': [{'role': 'user', 'content': prompt[:90_000]}]}
    req = urllib.request.Request(RUNTIME, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers={'Content-Type': 'application/json', 'User-Agent': 'ai-foundry-engineering-loop/v2'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as res:
        data = json.loads(res.read().decode('utf-8'))
    text = str(data.get('text') or '').strip()
    if not text:
        raise RuntimeError('runtime returned empty engineering output')
    return text


def extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.I)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('model output did not contain a JSON object')
    value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError('model JSON must be an object')
    return value


def safe_relpath(raw: Any) -> str:
    value = str(raw or '').strip().replace('\\', '/')
    if not value or value.startswith('/'):
        raise ValueError('file path must be relative')
    p = PurePosixPath(value)
    if any(part in ('', '.', '..') for part in p.parts) or '..' in p.parts:
        raise ValueError(f'unsafe file path: {value}')
    normalized = str(p)
    if normalized.startswith('.git/') or normalized == '.git':
        raise ValueError('writing .git is forbidden')
    return normalized


def normalize_files(value: Any, key: str = 'files') -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f'{key} must be a non-empty list')
    if len(value) > MAX_FILES:
        raise ValueError(f'too many files: {len(value)} > {MAX_FILES}')
    out, seen, total = [], set(), 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('file entry must be an object')
        path = safe_relpath(item.get('path'))
        content = str(item.get('content') or '')
        if len(content) > MAX_FILE_CHARS:
            raise ValueError(f'file too large: {path}')
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise ValueError('generated project exceeds total size limit')
        if path in seen:
            raise ValueError(f'duplicate file path: {path}')
        seen.add(path)
        out.append({'path': path, 'content': content})
    return out


def validate_command(command: Any) -> str:
    cmd = str(command or '').strip()
    if not cmd or len(cmd) > 1000:
        raise ValueError('invalid test command')
    if FORBIDDEN_SHELL.search(cmd):
        raise ValueError(f'shell metacharacters are forbidden: {cmd}')
    parts = shlex.split(cmd)
    if not parts or parts[0] not in ALLOWED_EXECUTABLES:
        raise ValueError(f'executable not allowed: {parts[0] if parts else ""}')
    forbidden_args = {'publish', 'deploy', 'login', 'logout', 'token', 'whoami'}
    if any(p.lower() in forbidden_args for p in parts[1:]):
        raise ValueError(f'command action not allowed: {cmd}')
    return cmd


def normalize_commands(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError('test_commands must be a list')
    if len(value) > MAX_COMMANDS:
        raise ValueError(f'too many test commands: {len(value)} > {MAX_COMMANDS}')
    return [validate_command(v) for v in value]


def scrubbed_env() -> dict[str, str]:
    env = {}
    for key, value in os.environ.items():
        if SENSITIVE_ENV.search(key) or key.startswith('ACTIONS_ID_TOKEN_') or key in {'GITHUB_TOKEN', 'GH_TOKEN'}:
            continue
        env[key] = value
    env['CI'] = 'true'
    env['NO_COLOR'] = '1'
    return env


def write_files(root: Path, files: list[dict[str, str]]) -> None:
    for item in files:
        dest = root / item['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item['content'], encoding='utf-8')


def run_commands(root: Path, commands: list[str]) -> list[dict[str, Any]]:
    results, env = [], scrubbed_env()
    for command in commands:
        started = time.time()
        try:
            proc = subprocess.run(shlex.split(command), cwd=root, env=env, capture_output=True, text=True, timeout=120, check=False)
            results.append({'command': command, 'exit_code': proc.returncode, 'stdout': (proc.stdout or '')[-MAX_LOG_CHARS:], 'stderr': (proc.stderr or '')[-MAX_LOG_CHARS:], 'duration_ms': int((time.time() - started) * 1000)})
        except subprocess.TimeoutExpired as exc:
            results.append({'command': command, 'exit_code': 124, 'stdout': str(exc.stdout or '')[-MAX_LOG_CHARS:], 'stderr': 'command timed out after 120 seconds', 'duration_ms': 120_000})
    return results


def http_smoke(root: Path, expected_contains: str) -> dict[str, Any]:
    if not (root / 'index.html').is_file():
        return {'attempted': False, 'passed': True, 'reason': 'no index.html'}
    proc = subprocess.Popen([sys.executable, '-m', 'http.server', '8765', '--bind', '127.0.0.1'], cwd=root, env=scrubbed_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        body, error = '', ''
        for _ in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8765/', timeout=2) as res:
                    body = res.read().decode('utf-8', errors='replace')
                    if res.status == 200:
                        break
            except Exception as exc:
                error = str(exc)
                time.sleep(0.2)
        passed = bool(body) and (not expected_contains or expected_contains in body)
        return {'attempted': True, 'passed': passed, 'http_200': bool(body), 'expected_contains': expected_contains, 'contains_ok': (not expected_contains or expected_contains in body), 'error': error if not body else ''}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def project_context(root: Path) -> str:
    chunks, used = [], 0
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith('.git/'):
            continue
        try:
            text = path.read_text(encoding='utf-8')[:20_000]
        except UnicodeDecodeError:
            continue
        if used + len(text) > 60_000:
            break
        chunks.append(f'FILE {rel}\n{text}')
        used += len(text)
    return '\n\n'.join(chunks)


def failed_evidence(command_results: list[dict[str, Any]], smoke: dict[str, Any]) -> str:
    failures = [r for r in command_results if int(r.get('exit_code', 1)) != 0]
    return json.dumps({'command_failures': failures, 'http_smoke': smoke}, ensure_ascii=False, indent=2)[-35_000:]


def verify(command_results: list[dict[str, Any]], smoke: dict[str, Any]) -> bool:
    return bool(command_results) and all(int(r.get('exit_code', 1)) == 0 for r in command_results) and bool(smoke.get('passed'))


def build_task_text(request: dict[str, Any]) -> str:
    messages = request.get('messages') if isinstance(request.get('messages'), list) else []
    if messages:
        lines = []
        for message in messages[-18:]:
            if not isinstance(message, dict):
                continue
            role, content = str(message.get('role') or '').upper(), str(message.get('content') or '').strip()
            if role in {'USER', 'ASSISTANT'} and content:
                lines.append(f'{role}: {content[:12_000]}')
        if lines:
            return '\n\n'.join(lines)
    return str(request.get('request_text') or 'Build a useful small software prototype.').strip()[:40_000]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', required=True)
    parser.add_argument('--out-root', required=True)
    parser.add_argument('--meta-out', required=True)
    parser.add_argument('--repair-rounds', type=int, default=3)
    args = parser.parse_args()
    payload = json.loads(Path(args.payload).read_text(encoding='utf-8'))
    job = payload.get('job') or {}
    request = job.get('request') or {}
    job_id = str(job.get('id') or 'engineering-canary')
    task_text = build_task_text(request)
    root = Path(args.out_root) / job_id
    root.mkdir(parents=True, exist_ok=False)
    initial = extract_json(post_runtime(INITIAL_SYSTEM, f'DEVELOPMENT REQUEST:\n{task_text}'))
    files = normalize_files(initial.get('files'))
    commands = normalize_commands(initial.get('test_commands'))
    expected_contains = str(initial.get('expected_contains') or '')[:500]
    write_files(root, files)
    history = []
    max_rounds = min(3, max(0, int(args.repair_rounds)))
    for round_index in range(max_rounds + 1):
        command_results = run_commands(root, commands)
        smoke = http_smoke(root, expected_contains)
        passed = verify(command_results, smoke)
        history.append({'round': round_index, 'commands': command_results, 'http_smoke': smoke, 'passed': passed})
        if passed or round_index >= max_rounds:
            break
        prompt = f'ORIGINAL REQUEST:\n{task_text}\n\nCURRENT PROJECT:\n{project_context(root)}\n\nFAILURE EVIDENCE:\n{failed_evidence(command_results, smoke)}'
        repair = extract_json(post_runtime(REPAIR_SYSTEM, prompt))
        replacements = normalize_files(repair.get('replace_files'), key='replace_files')
        commands = normalize_commands(repair.get('test_commands'))
        write_files(root, replacements)
        history[-1]['repair_reason'] = str(repair.get('reason') or '')[:2000]
        history[-1]['repair_files'] = [x['path'] for x in replacements]
    verified = bool(history and history[-1].get('passed'))
    final_files = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    meta = {'job_id': job_id, 'name': str(initial.get('name') or 'AI FOUNDRY Engineering Build')[:120], 'summary': str(initial.get('summary') or '')[:4000], 'profile': 'engineering-loop-v2', 'verified': verified, 'repair_rounds_used': max(0, len(history) - 1), 'history': history, 'files': final_files}
    Path(args.meta_out).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'job_id': job_id, 'verified': verified, 'rounds': len(history), 'files': final_files}, ensure_ascii=False))
    return 0 if verified else 2


if __name__ == '__main__':
    raise SystemExit(main())
