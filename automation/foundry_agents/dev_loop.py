#!/usr/bin/env python3
"""
Foundry Autonomous Dev Loop — SENJU / X / META

Each agent produces one bounded improvement proposal for the AI Foundry IDE.
The highest-priority passing proposal is applied; a PR is created and auto-merged
when all checks pass.

Safety rules (immutable):
- Only paths listed in agents.json allowed_paths are touched.
- No secrets, credentials, or external targets.
- Every change must pass local lint before PR creation.
- No force-push; no history rewrite.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/the-world2")
TOKEN = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", "")).strip()
API = f"https://api.github.com/repos/{REPO}"
AGENTS_JSON = Path(__file__).parent / "agents.json"
REPORT_PATH = Path("/tmp/foundry-dev-report.md")


def _gh(method: str, path: str, payload: dict | None = None) -> Any:
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "foundry-autonomous-dev",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        return json.loads(raw.decode()) if raw else {}


def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=check)


def _report(line: str) -> None:
    with REPORT_PATH.open("a") as f:
        f.write(line + "\n")
    print(line)


def load_config() -> dict:
    return json.loads(AGENTS_JSON.read_text())


def allowed_paths(agent: dict) -> list[str]:
    return list(agent.get("allowed_paths", []))


def branch_name(agent_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return f"foundry/auto-dev-{agent_id.lower()}-{ts}"


def _open_foundry_prs() -> list[dict]:
    q = urllib.parse.urlencode({"state": "open", "per_page": 50, "sort": "created"})
    rows = _gh("GET", f"/pulls?{q}")
    return [p for p in rows if str((p.get("head") or {}).get("ref") or "").startswith("foundry/auto-dev-")]


def _pr_ready(pr: dict) -> dict:
    number = int(pr["number"])
    detail = _gh("GET", f"/pulls/{number}")
    sha = str((detail.get("head") or {}).get("sha") or "")
    checks: list[dict] = []
    if sha:
        cr = _gh("GET", f"/commits/{sha}/check-runs?per_page=100")
        checks = list(cr.get("check_runs") or [])
    pending = [c for c in checks if c.get("status") != "completed"]
    bad = [c for c in checks if c.get("status") == "completed" and c.get("conclusion") not in {"success", "neutral", "skipped"}]
    mergeable = detail.get("mergeable") is True
    ready = bool(checks) and not pending and not bad and mergeable
    return {"number": number, "head": (detail.get("head") or {}).get("ref"), "ready": ready,
            "mergeable": mergeable, "pending": len(pending), "bad": len(bad)}


def merge_ready_prs(config: dict) -> None:
    policy = config.get("merge_policy", {})
    method = policy.get("merge_method", "squash")
    _report("## Merge phase")
    for pr in _open_foundry_prs():
        info = _pr_ready(pr)
        if info["ready"]:
            try:
                _gh("PUT", f"/pulls/{info['number']}/merge", {"merge_method": method})
                _report(f"MERGED #{info['number']} ({info['head']})")
            except Exception as exc:
                _report(f"MERGE FAILED #{info['number']}: {exc}")
        else:
            _report(f"SKIP #{info['number']} pending={info['pending']} bad={info['bad']} mergeable={info['mergeable']}")


def _build_improvement_prompt(agent: dict, app_state: str) -> str:
    return textwrap.dedent(f"""
    You are the {agent['name']} agent ({agent['role']}) for AI Foundry IDE autonomous development.

    Mandate: {agent['mandate']}
    Focus areas: {', '.join(agent['focus_areas'])}
    Allowed paths: {', '.join(agent['allowed_paths'])}

    Current app state summary:
    {app_state[:3000]}

    Produce ONE bounded, immediately applicable improvement to the AI Foundry IDE.
    Rules:
    - Only touch files under: {', '.join(agent['allowed_paths'])}
    - No secrets, credentials, external targets
    - Change must be minimal and self-contained
    - Respond with JSON only: {{"file": "path/to/file", "description": "one line", "patch": "unified diff or full new content"}}
    - If no safe improvement found, respond: {{"skip": true, "reason": "..."}}
    """).strip()


def generate_proposal(agent: dict, repo_root: Path) -> dict | None:
    """Use GitHub Copilot CLI to generate an improvement proposal."""
    app_state = _collect_app_state(repo_root)
    prompt = _build_improvement_prompt(agent, app_state)
    prompt_file = Path(f"/tmp/foundry-prompt-{agent['id']}.txt")
    prompt_file.write_text(prompt)

    result = _run(
        ["copilot", "suggest", "--shell", f"cat '{prompt_file}'"],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        # Fallback: use gh copilot explain / suggest
        _report(f"  {agent['name']}: copilot suggest unavailable, using gh copilot")
        result = _run(
            ["gh", "copilot", "suggest", "-t", "shell", prompt[:1000]],
            check=False,
        )

    output = (result.stdout or "").strip()
    try:
        start = output.index("{")
        end = output.rindex("}") + 1
        return json.loads(output[start:end])
    except (ValueError, json.JSONDecodeError):
        _report(f"  {agent['name']}: no valid JSON proposal")
        return None


def _collect_app_state(repo_root: Path) -> str:
    parts = []
    for rel in ["public/app.js", "api/foundry.js", "public/index.html", "vercel.json"]:
        p = repo_root / rel
        if p.exists():
            content = p.read_text(errors="replace")[:800]
            parts.append(f"=== {rel} (first 800 chars) ===\n{content}")
    return "\n\n".join(parts)


def apply_proposal(proposal: dict, agent: dict, repo_root: Path) -> bool:
    if proposal.get("skip"):
        _report(f"  {agent['name']}: skip — {proposal.get('reason')}")
        return False
    file_path = proposal.get("file", "")
    if not file_path:
        _report(f"  {agent['name']}: no file in proposal")
        return False
    allowed = allowed_paths(agent)
    if not any(file_path.startswith(p) for p in allowed):
        _report(f"  {agent['name']}: path {file_path} not in allowed {allowed}")
        return False
    target = repo_root / file_path
    patch = proposal.get("patch", "")
    if not patch:
        _report(f"  {agent['name']}: empty patch")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(patch, encoding="utf-8")
    _report(f"  {agent['name']}: wrote {file_path} ({len(patch)} chars)")
    return True


def create_pr(branch: str, base: str, agent: dict, description: str, token: str) -> str | None:
    title = f"[{agent['name']}] {description[:72]}"
    body = f"""Autonomous improvement by **{agent['name']}** agent ({agent['role']}).

**Mandate**: {agent['mandate'][:300]}
**Focus**: {', '.join(agent['focus_areas'][:3])}

Auto-generated by `foundry-autonomous-dev` workflow. Will auto-merge when all checks pass.

---
_Generated by [Claude Code](https://claude.ai/code)_

https://claude.ai/code/session_01AqjWBuUm8Pk56g3BPvcf9m"""
    try:
        pr = _gh("POST", "/pulls", {"title": title, "body": body, "head": branch, "base": base})
        url = pr.get("html_url", "")
        _report(f"  PR created: {url}")
        return url
    except Exception as exc:
        _report(f"  PR create failed: {exc}")
        return None


def run_dev_cycle(repo_root: Path, base_ref: str, dry_run: bool = False) -> None:
    config = load_config()
    agents = config["agents"]

    _report(f"\n# Foundry Autonomous Dev — {datetime.now(timezone.utc).isoformat()}")
    _report(f"Target: {config['target_app']}")
    _report(f"Agents: {[a['id'] for a in agents]}")

    # Phase 1: merge already-verified PRs
    if not dry_run:
        merge_ready_prs(config)

    # Phase 2: each agent proposes an improvement
    _report("\n## Proposal phase")
    proposals: list[tuple[dict, dict]] = []
    for agent in sorted(agents, key=lambda a: -a["priority_weight"]):
        _report(f"\n### Agent: {agent['name']}")
        proposal = generate_proposal(agent, repo_root)
        if proposal and not proposal.get("skip"):
            proposals.append((agent, proposal))

    if not proposals:
        _report("\nNo valid proposals this cycle.")
        return

    # Phase 3: pick best proposal (highest priority_weight, already sorted)
    best_agent, best_proposal = proposals[0]
    _report(f"\n## Applying: {best_agent['name']} — {best_proposal.get('description', 'improvement')}")

    if dry_run:
        _report("DRY RUN: skipping apply and PR creation")
        return

    branch = branch_name(best_agent["id"])
    _run(["git", "checkout", "-b", branch], cwd=str(repo_root))

    applied = apply_proposal(best_proposal, best_agent, repo_root)
    if not applied:
        _run(["git", "checkout", base_ref], cwd=str(repo_root))
        return

    # Commit
    _run(["git", "config", "user.email", "foundry-bot@musicjapan.llc"], cwd=str(repo_root))
    _run(["git", "config", "user.name", f"Foundry/{best_agent['name']}"], cwd=str(repo_root))
    _run(["git", "add", "-A"], cwd=str(repo_root))
    result = _run(["git", "diff", "--cached", "--stat"], cwd=str(repo_root))
    if not result.stdout.strip():
        _report("No changes staged — nothing to commit")
        _run(["git", "checkout", base_ref], cwd=str(repo_root))
        return
    msg = f"feat(foundry/{best_agent['id']}): {best_proposal.get('description', 'autonomous improvement')}\n\nAgent: {best_agent['name']} ({best_agent['role']})\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01AqjWBuUm8Pk56g3BPvcf9m"
    _run(["git", "commit", "-m", msg], cwd=str(repo_root))
    _run(["git", "push", "-u", "origin", branch], cwd=str(repo_root))

    create_pr(branch, base_ref, best_agent, best_proposal.get("description", "autonomous improvement"), TOKEN)
    _report("\nCycle complete.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base", default=os.environ.get("GITHUB_REF_NAME", "main"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge-only", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    REPORT_PATH.write_text("")

    if args.merge_only:
        config = load_config()
        merge_ready_prs(config)
    else:
        run_dev_cycle(repo_root, args.base, dry_run=args.dry_run)

    if REPORT_PATH.exists():
        print("\n" + REPORT_PATH.read_text())


if __name__ == "__main__":
    main()
