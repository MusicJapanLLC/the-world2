#!/usr/bin/env python3
"""SHA-aware PR Traffic Controller.

Classifies open PRs (READY, REBASE, REPAIR, SUPERSEDED, BLOCKED, REVIEW),
binds classifications to exact head/base SHAs, detects file & objective overlaps,
prioritizes repo-wide blockers, routes next actions to specific agents,
and maintains a durable status artifact without per-PR comment spam.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

CLASSIFICATIONS = {"READY", "REBASE", "REPAIR", "SUPERSEDED", "BLOCKED", "REVIEW"}
AGENTS = {"Jules", "OpenHands", "Claude-human", "Senju-R&D", "FOUNDRY"}

GOVERNANCE_SECURITY_PATHS = {
    "SECURITY.md",
    "FAITH.md",
    "CLAUDE.md",
    "company-society/",
    "STANDMENT_SECURITY_PORTFOLIO.md",
    ".github/workflows/security",
    ".github/agents/",
}

SENJU_PATHS = {
    "senju/",
    "autonomous_redteam_lab/",
    "scripts/shadow_",
    "scripts/pentest_",
}

FOUNDRY_PATHS = {
    "ai_foundry/",
    "automation/ai_foundry/",
    ".github/workflows/ai-foundry",
    ".github/workflows/deploy-",
}


def parse_objective_hints(title: str, body: str) -> Set[str]:
    """Extract issue references (#123), prefixes (fix(...)), and keywords from title & body."""
    hints: Set[str] = set()
    text = f"{title}\n{body}"
    issue_refs = re.findall(r"#(\d+)", text)
    for ref in issue_refs:
        hints.add(f"issue:{ref}")

    scopes = re.findall(r"(?:fix|feat|refactor|docs|chore)\(([a-zA-Z0-9_\-]+)\)", text, re.IGNORECASE)
    for scope in scopes:
        hints.add(f"scope:{scope.lower()}")

    words = re.findall(r"\b[a-zA-Z0-9_\-]{4,}\b", title.lower())
    for w in words:
        if w not in {"with", "from", "that", "this", "have", "more", "test", "fix"}:
            hints.add(f"title:{w}")
    return hints


def calculate_overlap(
    pr1: Dict[str, Any], pr2: Dict[str, Any]
) -> Tuple[bool, float, List[str]]:
    """Detect overlap between pr1 and pr2 using file intersection + objective hints."""
    files1 = set(pr1.get("changed_files", []))
    files2 = set(pr2.get("changed_files", []))

    reasons: List[str] = []
    file_intersection = files1 & files2
    file_ratio = 0.0
    if files1 and files2:
        file_ratio = len(file_intersection) / min(len(files1), len(files2))

    if file_intersection:
        reasons.append(f"shared_files:{len(file_intersection)}")

    hints1 = parse_objective_hints(pr1.get("title", ""), pr1.get("body", ""))
    hints2 = parse_objective_hints(pr2.get("title", ""), pr2.get("body", ""))
    hint_intersection = hints1 & hints2

    if hint_intersection:
        reasons.append(f"shared_hints:{','.join(sorted(hint_intersection))}")

    is_overlapping = bool(file_ratio > 0.4 or (file_intersection and hint_intersection))
    return is_overlapping, file_ratio, reasons


def route_next_agent(
    pr: Dict[str, Any], classification: str, blockers: List[str]
) -> str:
    """Emit recommended_next_agent from {Jules, OpenHands, Claude-human, Senju-R&D, FOUNDRY}."""
    changed_files = pr.get("changed_files", [])

    if any(any(f.startswith(p) for p in SENJU_PATHS) for f in changed_files):
        return "Senju-R&D"

    if any(any(f.startswith(p) for p in FOUNDRY_PATHS) for f in changed_files):
        return "FOUNDRY"

    if classification == "REVIEW" or any(
        any(f.startswith(p) or p in f for p in GOVERNANCE_SECURITY_PATHS)
        for f in changed_files
    ):
        return "Claude-human"

    if classification in {"REBASE", "REPAIR"}:
        if len(changed_files) >= 5 or "complex_conflict" in pr.get("reasons", []):
            return "OpenHands"

    return "Jules"


def is_classification_valid(
    stored_entry: Dict[str, Any], current_pr: Dict[str, Any]
) -> bool:
    """Mark stale classifications invalid when head or base changes."""
    if not stored_entry or not current_pr:
        return False

    stored_head = stored_entry.get("head_sha")
    stored_base = stored_entry.get("observed_base_sha")

    current_head = current_pr.get("head_sha")
    current_base = current_pr.get("base_sha") or current_pr.get("observed_base_sha")

    if not stored_head or not current_head:
        return False

    return (stored_head == current_head) and (stored_base == current_base)


def should_dispatch_ci(
    classification: str, is_stale: bool, is_security_sensitive: bool = False
) -> bool:
    """Reduce redundant CI dispatch for SUPERSEDED or stale PRs without weakening security semantics."""
    if is_security_sensitive:
        return True

    if classification == "SUPERSEDED":
        return False

    if is_stale and classification in {"SUPERSEDED", "BLOCKED"}:
        return False

    return True


def fetch_open_prs_from_github(repo: str, token: str) -> List[Dict[str, Any]]:
    """Fetch open PRs and their changed files via GitHub API."""
    owner, name = repo.split("/", 1)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-traffic-controller",
    }
    url = f"https://api.github.com/repos/{owner}/{name}/pulls?state=open&per_page=100"
    req = urllib.request.Request(url, headers=headers)
    prs: List[Dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            raw_prs = json.loads(raw.decode("utf-8")) if raw else []

        for item in raw_prs:
            pr_num = item.get("number")
            if not isinstance(pr_num, int):
                continue

            detail_item = item
            detail_url = f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_num}"
            detail_req = urllib.request.Request(detail_url, headers=headers)
            try:
                with urllib.request.urlopen(detail_req, timeout=30) as d_resp:
                    d_raw = d_resp.read()
                    if d_raw:
                        detail_item = json.loads(d_raw.decode("utf-8"))
            except Exception:
                pass

            files_url = f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_num}/files?per_page=100"
            files_req = urllib.request.Request(files_url, headers=headers)
            changed_files: List[str] = []
            try:
                with urllib.request.urlopen(files_req, timeout=30) as f_resp:
                    f_raw = f_resp.read()
                    if f_raw:
                        f_list = json.loads(f_raw.decode("utf-8"))
                        changed_files = [
                            f.get("filename")
                            for f in f_list
                            if isinstance(f, dict) and f.get("filename")
                        ]
            except Exception:
                pass

            prs.append({
                "number": pr_num,
                "title": item.get("title", ""),
                "body": item.get("body") or "",
                "head_sha": item.get("head", {}).get("sha", ""),
                "base_sha": item.get("base", {}).get("sha", ""),
                "state": item.get("state", "open"),
                "draft": item.get("draft", False),
                "mergeable": detail_item.get("mergeable"),
                "mergeable_state": detail_item.get("mergeable_state"),
                "changed_files": changed_files,
            })
    except Exception as exc:
        print(f"Warning: Failed to fetch open PRs from GitHub API: {exc}")

    return prs


def classify_pr(
    pr: Dict[str, Any],
    repo_wide_blockers: List[str],
    all_open_prs: List[Dict[str, Any]],
    merged_prs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Classify open PR into READY / REBASE / REPAIR / SUPERSEDED / BLOCKED / REVIEW."""
    pr_num = pr.get("number")
    head_sha = pr.get("head_sha", "")
    base_sha = pr.get("base_sha", "") or pr.get("observed_base_sha", "")
    changed_files = pr.get("changed_files", [])
    title = pr.get("title", "")
    body = pr.get("body", "")

    reasons: List[str] = []
    blockers: List[str] = []
    overlapping_prs: List[int] = []

    # 1. Overlap & Superseded Detection
    is_superseded = False
    superseded_by = None

    candidates = (merged_prs or []) + [
        other for other in all_open_prs if other.get("number") != pr_num
    ]
    for other in candidates:
        overlapping, score, overlap_reasons = calculate_overlap(pr, other)
        other_num = other.get("number")
        if overlapping and isinstance(other_num, int):
            overlapping_prs.append(other_num)

        other_body = other.get("body", "")
        if pr_num and re.search(r"supersedes\s+#?" + str(pr_num) + r"\b", other_body, re.IGNORECASE):
            is_superseded = True
            superseded_by = other_num
            reasons.append(f"Explicitly superseded by #{other_num}")
            break

        if set(changed_files) and set(changed_files) == set(other.get("changed_files", [])):
            if other.get("is_merged") or (other_num and pr_num and other_num > pr_num):
                is_superseded = True
                superseded_by = other_num
                reasons.append(f"Subsumed by #{other_num} (identical changed files)")
                break

    if re.search(r"superseded\s+by\s+#?\d+", body, re.IGNORECASE):
        is_superseded = True
        reasons.append("Marked superseded in PR body")

    if is_superseded:
        classification = "SUPERSEDED"
    # 2. Repo-wide Blockers Check (Evaluated BEFORE feature-level blockers)
    elif repo_wide_blockers:
        classification = "BLOCKED"
        blockers.extend([f"repo-wide: {b}" for b in repo_wide_blockers])
        reasons.append("Blocked by repository-wide issue or CI status")
    # 3. REBASE Check
    elif pr.get("mergeable") is False or pr.get("mergeable_state") in {"behind", "dirty", "conflict"}:
        classification = "REBASE"
        reasons.append(f"Merge conflict or behind base branch (mergeable_state={pr.get('mergeable_state')})")
    # 4. REPAIR Check
    elif pr.get("ci_status") == "failure" or pr.get("has_failing_tests"):
        classification = "REPAIR"
        reasons.append("CI checks failing on head SHA")
    # 5. Feature-level Blockers Check
    elif pr.get("feature_blockers") or re.search(r"depends\s+on\s+#\d+", body, re.IGNORECASE):
        classification = "BLOCKED"
        deps = pr.get("feature_blockers", [])
        dep_matches = re.findall(r"depends\s+on\s+#(\d+)", body, re.IGNORECASE)
        for d in dep_matches:
            deps.append(f"pr:#{d}")
        blockers.extend([f"feature: {d}" for d in deps])
        reasons.append("Blocked by feature-level dependency")
    # 6. REVIEW Check
    elif (
        pr.get("draft")
        or pr.get("mergeable_state") == "blocked"
        or pr.get("needs_review")
        or any(any(f.startswith(p) or p in f for p in GOVERNANCE_SECURITY_PATHS) for f in changed_files)
    ):
        classification = "REVIEW"
        if pr.get("draft"):
            reasons.append("PR is in draft state")
        elif any(any(f.startswith(p) or p in f for p in GOVERNANCE_SECURITY_PATHS) for f in changed_files):
            reasons.append("PR touches governance or security sensitive files")
        else:
            reasons.append("Requires human / audit review")
    # 7. READY Check
    else:
        classification = "READY"
        reasons.append("Clean mergeable state with passing CI")

    is_sec = any(any(f.startswith(p) or p in f for p in GOVERNANCE_SECURITY_PATHS) for f in changed_files)
    next_agent = route_next_agent(pr, classification, blockers)
    suppress_ci = not should_dispatch_ci(classification, is_stale=False, is_security_sensitive=is_sec)

    return {
        "number": pr_num,
        "title": title,
        "head_sha": head_sha,
        "observed_base_sha": base_sha,
        "classification": classification,
        "valid": True,
        "recommended_next_agent": next_agent,
        "overlapping_prs": sorted(list(set(overlapping_prs))),
        "blockers": blockers,
        "reasons": reasons,
        "suppress_redundant_ci": suppress_ci,
        "is_security_sensitive": is_sec,
    }


def generate_status_report(
    prs: List[Dict[str, Any]],
    repo_wide_blockers: List[str],
    previous_report: Optional[Dict[str, Any]] = None,
    repo_name: str = "MusicJapanLLC/test",
    base_sha: str = "head",
) -> Dict[str, Any]:
    """Generate durable machine-readable status artifact."""
    prev_entries: Dict[int, Dict[str, Any]] = {}
    if previous_report and isinstance(previous_report.get("prs"), list):
        for entry in previous_report["prs"]:
            if isinstance(entry, dict) and entry.get("number"):
                prev_entries[entry["number"]] = entry

    classified_prs: List[Dict[str, Any]] = []
    counts = {c: 0 for c in CLASSIFICATIONS}
    agent_counts = {a: 0 for a in AGENTS}

    for pr in prs:
        res = classify_pr(pr, repo_wide_blockers, prs)
        p_num = pr.get("number")
        if isinstance(p_num, int) and p_num in prev_entries:
            valid = is_classification_valid(prev_entries[p_num], pr)
            if not valid:
                res["valid"] = False
                res["reasons"].append("Invalidated due to head/base SHA change since previous report")

        classified_prs.append(res)
        counts[res["classification"]] = counts.get(res["classification"], 0) + 1
        agent_counts[res["recommended_next_agent"]] = agent_counts.get(res["recommended_next_agent"], 0) + 1

    report = {
        "schema": "pr-traffic-control/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo_name,
        "observed_base_sha": base_sha,
        "repo_wide_blockers": repo_wide_blockers,
        "summary": {
            "total_open_prs": len(prs),
            "classifications": counts,
            "recommended_agents": agent_counts,
            "suppressed_ci_prs": sum(1 for p in classified_prs if p.get("suppress_redundant_ci")),
        },
        "prs": classified_prs,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="PR Traffic Controller")
    parser.add_argument("--input", help="JSON file containing mock/fetched open PRs")
    parser.add_argument("--out", default="reports/pr-traffic/status.json", help="Output status artifact JSON path")
    parser.add_argument("--repo-blockers", nargs="*", default=[], help="Repository-wide blocker notes/issues")
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    input_prs: List[Dict[str, Any]] = []
    if args.input and Path(args.input).exists():
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        input_prs = data if isinstance(data, list) else data.get("prs", [])
    elif token:
        input_prs = fetch_open_prs_from_github(repo, token)

    out_path = Path(args.out)
    prev_report = None
    if out_path.exists():
        try:
            prev_report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            prev_report = None

    report = generate_status_report(
        prs=input_prs,
        repo_wide_blockers=args.repo_blockers,
        previous_report=prev_report,
        repo_name=repo,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
