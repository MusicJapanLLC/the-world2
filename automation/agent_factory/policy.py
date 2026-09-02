#!/usr/bin/env python3
"""Fail-closed diff policy for Agent Factory champion changes."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ALLOWED_PREFIXES = (
    "automation/ai_foundry/",
    "automation/world/",
    "automation/security/",
    "standment-security/",
    "value-lab/",
    "docs/",
)
BLOCKED_EXACT = {"PORTFOLIO.md", "ops/system-registry.json"}
BLOCKED_PREFIXES = (
    ".github/",
    "automation/agent_factory/",
    "senju/",
    "outside-world/",
    "tomoki-agents/",
    "ops/",
)
from automation.world.adaptive_budget import compute_adaptive_budget, BASE_MAX_FILES, BASE_MAX_CHANGED_LINES

MAX_FILES = BASE_MAX_FILES
MAX_CHANGED_LINES = BASE_MAX_CHANGED_LINES


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8", errors="replace")


def inspect_diff(base: str) -> dict[str, Any]:
    names = [x.strip() for x in _git("diff", "--name-only", base, "--").splitlines() if x.strip()]
    numstat = _git("diff", "--numstat", base, "--")

    first_file = names[0] if names else "automation/world/"
    adaptive = compute_adaptive_budget(first_file, base_files=MAX_FILES, base_lines=MAX_CHANGED_LINES)
    effective_max_files = adaptive.max_files
    effective_max_lines = adaptive.max_changed_lines

    changed_lines = 0
    stat_rows = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add, delete, path = parts[0], parts[1], parts[2]
        try:
            a = int(add)
            d = int(delete)
        except ValueError:
            a = d = effective_max_lines + 1
        changed_lines += a + d
        stat_rows.append({"path": path, "added": a, "deleted": d})

    violations: list[str] = []
    if not names:
        violations.append("no_change")
    if len(names) > effective_max_files:
        violations.append(f"too_many_files:{len(names)}>{effective_max_files}")
    if changed_lines > effective_max_lines:
        violations.append(f"too_many_changed_lines:{changed_lines}>{effective_max_lines}")

    for raw in names:
        path = raw.replace("\\", "/")
        if path in BLOCKED_EXACT:
            violations.append(f"blocked_path:{path}")
            continue
        if path.startswith(BLOCKED_PREFIXES):
            violations.append(f"blocked_path:{path}")
            continue
        if not path.startswith(ALLOWED_PREFIXES):
            violations.append(f"outside_allowlist:{path}")

    return {
        "schema": "agent-factory-policy/v1",
        "base": base,
        "files": names,
        "file_count": len(names),
        "changed_lines": changed_lines,
        "numstat": stat_rows,
        "max_files": effective_max_files,
        "max_changed_lines": effective_max_lines,
        "adaptive_budget_reason": adaptive.reason,
        "violations": violations,
        "allowed": bool(names) and not violations,
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        "# Agent Factory Champion Policy",
        "",
        f"- allowed: **{result.get('allowed')}**",
        f"- files: {result.get('file_count')} / {result.get('max_files')}",
        f"- changed lines: {result.get('changed_lines')} / {result.get('max_changed_lines')}",
        "",
        "## Files",
    ]
    lines.extend(f"- `{p}`" for p in result.get("files") or [])
    lines += ["", "## Violations"]
    lines.extend(f"- {v}" for v in (result.get("violations") or ["NONE"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="HEAD")
    p.add_argument("--json", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    result = inspect_diff(args.base)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(result), encoding="utf-8")
    print(json.dumps({"allowed": result["allowed"], "files": result["file_count"], "changed_lines": result["changed_lines"], "violations": result["violations"]}, ensure_ascii=False))
    return 0 if result["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
