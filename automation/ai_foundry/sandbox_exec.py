#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Iterable

MAX_LOG_CHARS = 16000
MAX_COMMANDS = 6
DEFAULT_TIMEOUT = 180

_ALLOWED_PREFIXES = (
    ("node", "--check"),
    ("python", "-m", "compileall"),
    ("python3", "-m", "compileall"),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("python3", "-m", "unittest"),
    ("pytest",),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("go", "test"),
    ("cargo", "test"),
    ("cargo", "check"),
)


def _safe_argv(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("empty test command")
    if any(token in command for token in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        raise ValueError(f"shell operators are not allowed: {command}")
    argv = shlex.split(command, posix=True)
    if not argv:
        raise ValueError("empty argv")
    if not any(tuple(argv[: len(prefix)]) == prefix for prefix in _ALLOWED_PREFIXES):
        raise ValueError(f"unsupported sandbox command: {command}")
    return argv


def sanitized_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "RUNNER_TEMP")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def autodetect_commands(repo: Path, changed_files: Iterable[str]) -> list[str]:
    changed = list(changed_files)
    commands: list[str] = []
    py_files = [p for p in changed if p.endswith(".py")]
    js_files = [p for p in changed if p.endswith((".js", ".mjs", ".cjs"))]
    if py_files:
        commands.append("python -m compileall " + " ".join(shlex.quote(p) for p in py_files[:20]))
    for path in js_files[:12]:
        commands.append("node --check " + shlex.quote(path))
    if (repo / "pytest.ini").exists() or (repo / "pyproject.toml").exists():
        if any("test" in Path(p).name.lower() for p in changed):
            commands.append("python -m pytest -q")
    if (repo / "package.json").exists():
        try:
            package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
            scripts = package.get("scripts") or {}
            if "test" in scripts:
                commands.append("npm test")
            elif "build" in scripts:
                commands.append("npm run build")
        except Exception:
            pass
    if (repo / "go.mod").exists():
        commands.append("go test ./...")
    if (repo / "Cargo.toml").exists():
        commands.append("cargo test")
    deduped: list[str] = []
    for command in commands:
        if command not in deduped:
            deduped.append(command)
    return deduped[:MAX_COMMANDS]


def run_commands(commands: Iterable[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> dict:
    results: list[dict] = []
    ok = True
    for index, command in enumerate(list(commands)[:MAX_COMMANDS], start=1):
        started = time.time()
        try:
            argv = _safe_argv(command)
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                env=sanitized_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = completed.stdout[-MAX_LOG_CHARS:]
            item = {
                "index": index,
                "command": command,
                "returncode": completed.returncode,
                "ok": completed.returncode == 0,
                "duration_seconds": round(time.time() - started, 3),
                "output": output,
            }
        except Exception as exc:
            item = {
                "index": index,
                "command": command,
                "returncode": -1,
                "ok": False,
                "duration_seconds": round(time.time() - started, 3),
                "output": f"sandbox error: {type(exc).__name__}: {exc}",
            }
        results.append(item)
        if not item["ok"]:
            ok = False
            break
    return {"ok": ok, "commands": results, "sandbox": "github-ephemeral-runner/scrubbed-env"}
