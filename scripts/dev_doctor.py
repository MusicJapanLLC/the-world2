#!/usr/bin/env python3
import json
import os
import glob
import re
import sys
import urllib.request
import urllib.error

def check_workflow_yamls(workflows_dir=".github/workflows"):
    results = {
        "files_checked": 0,
        "parse_errors": [],
        "duplicated_triggers": [],
        "duplicate_workflow_names": [],
        "missing_script_refs": []
    }

    if not os.path.exists(workflows_dir):
        return results

    workflow_files = glob.glob(os.path.join(workflows_dir, "*.yml")) + glob.glob(os.path.join(workflows_dir, "*.yaml"))
    results["files_checked"] = len(workflow_files)

    workflow_names = {}
    triggers_map = {}

    for filepath in workflow_files:
        filename = os.path.basename(filepath)
        content = ""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            results["parse_errors"].append(f"{filename}: Failed to read file: {e}")
            continue

        if not content.strip():
            results["parse_errors"].append(f"{filename}: File is empty")
            continue

        name_match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        if name_match:
            wf_name = name_match.group(1).strip().strip("'\"")
            if wf_name in workflow_names:
                results["duplicate_workflow_names"].append(
                    f"Workflow name '{wf_name}' duplicated in {filename} and {workflow_names[wf_name]}"
                )
            else:
                workflow_names[wf_name] = filename

        # Search for references to local scripts
        script_refs = re.findall(r"(?:python|bash|sh|node|\./)\s+([a-zA-Z0-9_\-/\.]+\.(?:py|sh|js|ts))", content)
        for ref in set(script_refs):
            ref_clean = ref.lstrip("./")
            if (ref_clean.startswith("scripts/") or ref_clean.startswith("automation/") or "/" in ref_clean) and not ref_clean.startswith("http"):
                if not os.path.exists(ref_clean):
                    results["missing_script_refs"].append(f"{filename} references missing script '{ref_clean}'")

        # Check triggers
        on_match = re.search(r"^on:\s*(.+)$", content, re.MULTILINE)
        if on_match:
            trigger_str = on_match.group(1).strip()
            triggers_map.setdefault(trigger_str, []).append(filename)

    for trigger, files in triggers_map.items():
        if len(files) > 3 and trigger not in ["workflow_dispatch", "[workflow_dispatch]"]:
            results["duplicated_triggers"].append(f"Trigger '{trigger}' shared by {len(files)} workflows: {', '.join(files[:5])}")

    return results


def check_manifests_and_lockfiles(repo_root="."):
    results = {
        "manifests_found": [],
        "lockfiles_found": [],
        "warnings": []
    }

    manifest_lock_pairs = [
        ("package.json", "package-lock.json", "Node.js / npm"),
        ("package.json", "yarn.lock", "Node.js / Yarn"),
        ("package.json", "bun.lockb", "Node.js / Bun"),
        ("requirements.txt", "requirements.lock", "Python pip"),
        ("Pipfile", "Pipfile.lock", "Python Pipenv"),
        ("pyproject.toml", "poetry.lock", "Python Poetry")
    ]

    for manifest, lockfile, tech in manifest_lock_pairs:
        manifest_path = os.path.join(repo_root, manifest)
        lockfile_path = os.path.join(repo_root, lockfile)

        if os.path.exists(manifest_path):
            if manifest not in results["manifests_found"]:
                results["manifests_found"].append(manifest)
            if os.path.exists(lockfile_path):
                if lockfile not in results["lockfiles_found"]:
                    results["lockfiles_found"].append(lockfile)
            else:
                if tech == "Node.js / npm" and not any(os.path.exists(os.path.join(repo_root, l)) for l in ["yarn.lock", "bun.lockb", "pnpm-lock.yaml"]):
                    results["warnings"].append(f"{manifest} present but no lockfile ({lockfile}) found.")

    return results


def check_discoverable_commands(repo_root="."):
    commands = []

    pkg_json = os.path.join(repo_root, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                scripts = data.get("scripts", {})
                for name, cmd in scripts.items():
                    commands.append(f"npm run {name} -> `{cmd}`")
        except Exception:
            pass

    if os.path.exists(os.path.join(repo_root, "requirements.txt")) or glob.glob(os.path.join(repo_root, "**", "test_*.py"), recursive=True):
        commands.append("pytest (Python test suite)")

    if os.path.exists(os.path.join(repo_root, "Makefile")):
        commands.append("make (Makefile commands available)")

    return commands


def check_github_repo_health():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    results = {
        "api_available": False,
        "open_prs_count": 0,
        "stale_or_conflicting_prs": [],
        "recent_ci_failures": []
    }

    if not token or not repo:
        return results

    results["api_available"] = True
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "dev-doctor-script"
    }

    # Query open PRs
    prs_url = f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100"
    req = urllib.request.Request(prs_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            prs = json.loads(resp.read().decode("utf-8"))
            results["open_prs_count"] = len(prs)
            for pr in prs:
                pr_num = pr["number"]
                title = pr["title"]
                draft = pr.get("draft", False)
                base = pr.get("base", {}).get("ref")
                # Fetch detailed PR for mergeable state
                pr_detail_url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}"
                detail_req = urllib.request.Request(pr_detail_url, headers=headers)
                try:
                    with urllib.request.urlopen(detail_req) as dresp:
                        detail = json.loads(dresp.read().decode("utf-8"))
                        if detail.get("mergeable") is False or detail.get("mergeable_state") in ["dirty", "blocked"]:
                            results["stale_or_conflicting_prs"].append(
                                f"PR #{pr_num} ('{title}'): mergeable={detail.get('mergeable')}, state={detail.get('mergeable_state')}, base={base}, draft={draft}"
                            )
                except Exception:
                    pass
    except Exception as e:
        results["warnings"] = [f"Failed to fetch open PRs: {e}"]

    # Query recent workflow runs on default branch
    runs_url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=30"
    req = urllib.request.Request(runs_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            runs_data = json.loads(resp.read().decode("utf-8"))
            runs = runs_data.get("workflow_runs", [])
            for run in runs:
                if run.get("conclusion") == "failure":
                    results["recent_ci_failures"].append(
                        f"Workflow '{run.get('name')}' run #{run.get('run_number')} failed on branch '{run.get('head_branch')}' ({run.get('html_url')})"
                    )
    except Exception:
        pass

    return results


def generate_report():
    wf_results = check_workflow_yamls()
    pkg_results = check_manifests_and_lockfiles()
    cmd_results = check_discoverable_commands()
    gh_results = check_github_repo_health()

    report_lines = []
    report_lines.append("# 🩺 Development Environment & Repository Health Audit Report")
    report_lines.append("")

    report_lines.append("## 1. Workflow YAML & Script Reference Audit")
    report_lines.append(f"- **Workflows Checked**: {wf_results['files_checked']}")
    if wf_results['parse_errors']:
        report_lines.append(f"- **Parse Errors**: {len(wf_results['parse_errors'])}")
        for err in wf_results['parse_errors']:
            report_lines.append(f"  - ❌ {err}")
    else:
        report_lines.append("- **Parse Errors**: None (All workflows parseable)")

    if wf_results['duplicate_workflow_names']:
        report_lines.append("- **Duplicate Workflow Names**:")
        for dup in wf_results['duplicate_workflow_names']:
            report_lines.append(f"  - ⚠️ {dup}")

    if wf_results['missing_script_refs']:
        report_lines.append("- **Missing Script References**:")
        for missing in wf_results['missing_script_refs']:
            report_lines.append(f"  - ❌ {missing}")
    else:
        report_lines.append("- **Missing Script References**: None")

    if wf_results['duplicated_triggers']:
        report_lines.append("- **Frequent / Duplicated Triggers**:")
        for trig in wf_results['duplicated_triggers']:
            report_lines.append(f"  - ℹ️ {trig}")
    report_lines.append("")

    report_lines.append("## 2. Package Manifests & Lockfiles")
    report_lines.append(f"- **Manifests Found**: {', '.join(pkg_results['manifests_found']) if pkg_results['manifests_found'] else 'None'}")
    report_lines.append(f"- **Lockfiles Found**: {', '.join(pkg_results['lockfiles_found']) if pkg_results['lockfiles_found'] else 'None'}")
    if pkg_results['warnings']:
        for w in pkg_results['warnings']:
            report_lines.append(f"  - ⚠️ {w}")
    report_lines.append("")

    report_lines.append("## 3. Discoverable Test / Lint Commands")
    if cmd_results:
        for cmd in cmd_results:
            report_lines.append(f"- {cmd}")
    else:
        report_lines.append("- No standard test/lint commands discovered")
    report_lines.append("")

    report_lines.append("## 4. GitHub PR & CI Health")
    if gh_results['api_available']:
        report_lines.append(f"- **Open PRs**: {gh_results['open_prs_count']}")
        if gh_results['stale_or_conflicting_prs']:
            report_lines.append(f"- **Stale / Conflicting PRs ({len(gh_results['stale_or_conflicting_prs'])})**:")
            for pr in gh_results['stale_or_conflicting_prs'][:10]:
                report_lines.append(f"  - ⚠️ {pr}")
        else:
            report_lines.append("- **Stale / Conflicting PRs**: None")

        if gh_results['recent_ci_failures']:
            report_lines.append(f"- **Recent CI Failures ({len(gh_results['recent_ci_failures'])})**:")
            for fail in gh_results['recent_ci_failures'][:10]:
                report_lines.append(f"  - ❌ {fail}")
        else:
            report_lines.append("- **Recent CI Failures**: None")
    else:
        report_lines.append("- *GitHub API token not available; skipped remote PR/CI inspection.*")

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("*Audit generated automatically by `scripts/dev_doctor.py`.*")

    return "\n".join(report_lines)


def upsert_tracking_issue(report_body):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("GITHUB_TOKEN or GITHUB_REPOSITORY not set; skipping issue creation.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "dev-doctor-script",
        "Content-Type": "application/json"
    }

    issue_title = "[Doctor] Development Environment & Repository Health Report"

    search_url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100"
    req = urllib.request.Request(search_url, headers=headers)
    existing_issue_number = None

    try:
        with urllib.request.urlopen(req) as resp:
            issues = json.loads(resp.read().decode("utf-8"))
            for issue in issues:
                if issue.get("title") == issue_title and "pull_request" not in issue:
                    existing_issue_number = issue["number"]
                    break
    except Exception as e:
        print(f"Error searching for tracking issue: {e}")

    if existing_issue_number:
        update_url = f"https://api.github.com/repos/{repo}/issues/{existing_issue_number}"
        payload = json.dumps({"body": report_body, "state": "open"}).encode("utf-8")
        req = urllib.request.Request(update_url, data=payload, headers=headers, method="PATCH")
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"Updated tracking issue #{existing_issue_number}")
        except Exception as e:
            print(f"Failed to update tracking issue #{existing_issue_number}: {e}")
    else:
        create_url = f"https://api.github.com/repos/{repo}/issues"
        payload = json.dumps({"title": issue_title, "body": report_body}).encode("utf-8")
        req = urllib.request.Request(create_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                created = json.loads(resp.read().decode("utf-8"))
                print(f"Created tracking issue #{created.get('number')}")
        except Exception as e:
            print(f"Failed to create tracking issue: {e}")


if __name__ == "__main__":
    report = generate_report()
    print(report)

    with open("doctor_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    if "--upsert-issue" in sys.argv:
        upsert_tracking_issue(report)
