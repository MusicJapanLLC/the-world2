#!/usr/bin/env python3
"""Policy gate for autonomous THE WORLD repair patches."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ALLOWED_PREFIXES = (
    ".github/workflows/",
    "automation/world/",
    "company-society/",
    "senju/",
    "tomoki-agents/",
)
FORBIDDEN_FILES = {
    ".github/workflows/security-guard.yml",
    ".github/workflows/tomoki-forge.yml",
    "automation/world/self_heal_policy.py",
    "automation/world/self_heal_verify.sh",
    "automation/world/self_heal_merge.py",
    "automation/world/prompts/self-heal.md",
}
from automation.world.adaptive_budget import compute_adaptive_budget

MAX_FILES = 4
MAX_CHANGED_LINES = 400
FORBIDDEN_PATTERNS = [
    r"pull_request_target\s*:",
    r"workflow_run\s*:",
    r"repository_dispatch\s*:",
    r"issue_comment\s*:",
    r"permissions\s*:\s*write-all",
    r"runs-on\s*:\s*self-hosted",
    r"git\s+push\s+(-f|--force)",
    r"--allow-all-tools",
    r"--yolo",
    r"https://hooks\.slack\.com/services/",
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"gh[pousr]_[A-Za-z0-9_]{20,}",
    r"sk-[A-Za-z0-9_-]{20,}",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    names = [x for x in git("diff", "--name-only").splitlines() if x.strip()]
    if not names:
        print("SELF_HEAL_POLICY: no changes")
        return 0
    first_name = names[0] if names else ""
    adaptive = compute_adaptive_budget(first_name, base_files=MAX_FILES, base_lines=MAX_CHANGED_LINES)
    effective_max_files = adaptive.max_files
    effective_max_lines = adaptive.max_changed_lines

    if len(names) > effective_max_files:
        raise SystemExit(f"SELF_HEAL_POLICY: too many changed files: {len(names)} > {effective_max_files}")

    for name in names:
        if name in FORBIDDEN_FILES:
            raise SystemExit(f"SELF_HEAL_POLICY: protected guardrail file changed: {name}")
        if not name.startswith(ALLOWED_PREFIXES):
            raise SystemExit(f"SELF_HEAL_POLICY: path outside repair allowlist: {name}")
        if any(part in name.lower() for part in ("secret", "credential", ".env", "token.json", "client_secret")):
            raise SystemExit(f"SELF_HEAL_POLICY: secret-like path is forbidden: {name}")

    numstat = git("diff", "--numstat").splitlines()
    changed_lines = 0
    for line in numstat:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        for value in parts[:2]:
            if value.isdigit():
                changed_lines += int(value)
    if changed_lines > effective_max_lines:
        raise SystemExit(f"SELF_HEAL_POLICY: patch too large: {changed_lines} > {effective_max_lines}")

    diff = git("diff", "--unified=0")
    added = "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, added, flags=re.IGNORECASE):
            raise SystemExit(f"SELF_HEAL_POLICY: forbidden pattern introduced: {pattern}")

    # A repair may fix a workflow permission typo, but it may not introduce new
    # repository write authority beyond workflows that already had it.
    for name in names:
        if not name.startswith(".github/workflows/"):
            continue
        before = subprocess.run(
            ["git", "show", f"HEAD:{name}"], text=True, capture_output=True, check=False
        ).stdout
        after = Path(name).read_text(encoding="utf-8") if Path(name).exists() else ""
        write_keys = ("contents: write", "actions: write", "pull-requests: write", "issues: write")
        for key in write_keys:
            if key in after and key not in before:
                raise SystemExit(f"SELF_HEAL_POLICY: repair may not introduce new workflow write authority: {name}: {key}")

    print(f"SELF_HEAL_POLICY: PASS files={len(names)} changed_lines={changed_lines}")
    for name in names:
        print(f" - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
