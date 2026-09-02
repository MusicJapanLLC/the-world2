#!/usr/bin/env python3
"""Daily defensive-security R&D loop for Standment.

Designed to run unattended in GitHub Actions. It only performs passive public
research plus checks against this repository / CI sandbox. It does not probe,
exploit, authenticate to, or modify third-party systems.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPORTS = HERE / "reports"
MEMORY = HERE / "memory"
ARTIFACTS = HERE / "artifacts"
QUEUE_PATH = HERE / "research_queue.json"
STATE_PATH = MEMORY / "state.json"
CHAMPION_PATH = MEMORY / "champion.json"
FAILURE_PATH = MEMORY / "failures.jsonl"

CISA_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
GITHUB_ADVISORIES = "https://api.github.com/advisories?per_page=20&sort=published&direction=desc"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_failure(stage: str, message: str) -> None:
    FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": utcnow().isoformat(), "stage": stage, "message": message[:500]}
    with FAILURE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def fetch_json(url: str) -> Any:
    headers = {
        "User-Agent": "Standment-Defensive-RD/1.0",
        "Accept": "application/json",
    }
    token = os.getenv("GITHUB_TOKEN")
    if "api.github.com" in url and token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as res:
        return json.loads(res.read().decode("utf-8"))


def collect_threat_intel() -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        kev = fetch_json(CISA_KEV)
        vulns = kev.get("vulnerabilities", []) if isinstance(kev, dict) else []
        for item in vulns[-20:]:
            findings.append(
                {
                    "source": "CISA KEV",
                    "id": item.get("cveID", "unknown"),
                    "vendor": item.get("vendorProject", ""),
                    "product": item.get("product", ""),
                    "date_added": item.get("dateAdded", ""),
                    "action": item.get("requiredAction", ""),
                    "url": CISA_KEV,
                }
            )
    except Exception as exc:  # network failure must not kill the whole R&D loop
        errors.append(f"CISA KEV fetch failed: {exc}")
        append_failure("threat-intel:cisa", str(exc))

    try:
        advisories = fetch_json(GITHUB_ADVISORIES)
        if isinstance(advisories, list):
            for item in advisories[:20]:
                findings.append(
                    {
                        "source": "GitHub Advisory Database",
                        "id": item.get("ghsa_id") or item.get("cve_id") or "unknown",
                        "cve": item.get("cve_id") or "",
                        "severity": item.get("severity", "unknown"),
                        "published_at": item.get("published_at", ""),
                        "summary": item.get("summary", ""),
                        "url": item.get("html_url", ""),
                    }
                )
    except Exception as exc:
        errors.append(f"GitHub advisory fetch failed: {exc}")
        append_failure("threat-intel:github", str(exc))

    return findings, errors


def secret_hygiene_scan() -> list[dict[str, str]]:
    """Conservative secret-pattern scan. Never writes matched secret values."""
    rules = {
        "private-key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
        "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "generic-api-key": re.compile(r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][^'\"]{12,}"),
    }
    findings: list[dict[str, str]] = []
    allowed = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".md", ".env", ".txt", ".sh"}

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in allowed:
            continue
        if path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in rules.items():
            if pattern.search(text):
                findings.append({"path": str(path.relative_to(ROOT)), "rule": name})
    return findings[:100]


def run_repo_audit() -> dict[str, Any]:
    workflow_dir = ROOT / ".github" / "workflows"
    workflow_names = {p.name for p in workflow_dir.glob("*.yml")} | {p.name for p in workflow_dir.glob("*.yaml")}

    controls = {
        "security_policy": (ROOT / "SECURITY.md").exists(),
        "codeql": any("codeql" in x.lower() for x in workflow_names),
        "dependency_review": any("dependency-review" in x.lower() for x in workflow_names),
        "dependency_audit": any("dependency-audit" in x.lower() for x in workflow_names),
        "self_heal": (ROOT / "automation" / "world" / "self_heal_engine.py").exists(),
        "control_plane": (ROOT / "automation" / "control_plane" / "manager.py").exists(),
        "realtime_kernel": (ROOT / "automation" / "world" / "realtime_kernel.py").exists(),
        "gitignore": (ROOT / ".gitignore").exists(),
        "env_example": (ROOT / ".env.example").exists(),
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(ROOT / "automation"), str(HERE)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        compile_ok = proc.returncode == 0
        compile_note = (proc.stderr or proc.stdout).strip()[-1000:]
    except Exception as exc:
        compile_ok = False
        compile_note = str(exc)
        append_failure("compile-check", str(exc))

    secrets = secret_hygiene_scan()
    passed = sum(1 for v in controls.values() if v)
    base_score = round(100 * passed / max(len(controls), 1), 1)
    score = max(0.0, base_score - min(25.0, len(secrets) * 5.0) - (0 if compile_ok else 15.0))

    return {
        "controls": controls,
        "workflow_count": len(workflow_names),
        "compile_ok": compile_ok,
        "compile_note": compile_note,
        "secret_hygiene_findings": secrets,
        "maturity_score": round(score, 1),
    }


def update_research_queue(intel: list[dict[str, Any]]) -> dict[str, Any]:
    queue = load_json(QUEUE_PATH, {"version": 1, "items": []})
    items = queue.setdefault("items", [])
    existing = {str(i.get("source_ref", "")) for i in items}

    # Prefer newest CISA KEV entries; defensive assessment only.
    kev = [x for x in intel if x.get("source") == "CISA KEV"]
    kev.sort(key=lambda x: str(x.get("date_added", "")), reverse=True)
    added = 0
    for finding in kev[:5]:
        ref = str(finding.get("id", "unknown"))
        if not ref or ref in existing:
            continue
        items.append(
            {
                "id": f"AUTO-{ref}",
                "title": f"Defensive exposure review: {ref}",
                "type": "defensive-assessment",
                "priority": 90,
                "status": "queued",
                "scope": "public-info-and-own-assets-only",
                "source_ref": ref,
                "success_metric": "Document exposure checks, mitigations, detection ideas and evidence without exploiting third parties",
            }
        )
        existing.add(ref)
        added += 1

    # Bound the queue so daily operation does not become an infinite backlog.
    if len(items) > 200:
        items[:] = items[-200:]
    save_json(QUEUE_PATH, queue)
    return {"queue_size": len(items), "new_items": added}


def portfolio_score(audit: dict[str, Any], intel_count: int, queue_stats: dict[str, Any]) -> float:
    score = audit["maturity_score"] * 0.65
    score += min(15.0, intel_count * 0.5)
    score += min(10.0, queue_stats["queue_size"] * 0.5)
    score += 10.0 if audit["compile_ok"] else 0.0
    return round(min(100.0, score), 1)


def write_report(
    intel: list[dict[str, Any]], errors: list[str], audit: dict[str, Any], queue_stats: dict[str, Any], score: float
) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = utcnow().date().isoformat()
    path = REPORTS / f"{today}.md"

    recent = sorted(
        intel,
        key=lambda x: str(x.get("date_added") or x.get("published_at") or ""),
        reverse=True,
    )[:10]

    lines = [
        f"# Standment Security R&D — {today}",
        "",
        "## Executive summary",
        f"- R&D score: **{score}/100**",
        f"- Public defensive signals collected: **{len(intel)}**",
        f"- Research queue: **{queue_stats['queue_size']}** items (+{queue_stats['new_items']} today)",
        f"- Repository maturity score: **{audit['maturity_score']}/100**",
        f"- Python compile check: **{'PASS' if audit['compile_ok'] else 'FAIL'}**",
        f"- Secret-hygiene flags: **{len(audit['secret_hygiene_findings'])}** (paths/rules only; values are never reported)",
        "",
        "## Defensive intelligence",
    ]

    if not recent:
        lines.append("- No fresh external intelligence was available in this run.")
    for item in recent:
        title = item.get("id", "unknown")
        vendor = " ".join(x for x in [str(item.get("vendor", "")), str(item.get("product", ""))] if x).strip()
        summary = str(item.get("summary") or item.get("action") or "").replace("\n", " ")[:220]
        lines.append(f"- **{title}** {vendor} — {summary}".rstrip())

    lines.extend(["", "## Defensive control audit"])
    for key, value in audit["controls"].items():
        lines.append(f"- {'✅' if value else '⬜'} `{key}`")

    lines.extend(["", "## Secret hygiene"])
    if audit["secret_hygiene_findings"]:
        for finding in audit["secret_hygiene_findings"]:
            lines.append(f"- Review `{finding['path']}` for rule `{finding['rule']}`")
    else:
        lines.append("- No high-confidence secret-pattern flags found by the lightweight scanner.")

    lines.extend(["", "## Failures / degraded inputs"])
    if errors:
        lines.extend(f"- {err}" for err in errors)
    else:
        lines.append("- None recorded in this run.")

    lines.extend(
        [
            "",
            "## Next autonomous actions",
            "- Keep the highest-priority defensive assessments in the research queue.",
            "- Prefer measurable improvements to CI, dependency security, secret hygiene, recovery and evidence quality.",
            "- Record failed experiments instead of repeating them silently.",
            "- Promote changes only through branch/test/review/merge.",
            "",
            "## Research boundary",
            "Passive public research and own/authorized environments only. No unauthorized exploitation, credential bypass, persistence, destructive testing or third-party modification.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def update_memory(score: float, report: Path, audit: dict[str, Any]) -> dict[str, Any]:
    state = load_json(STATE_PATH, {"run_count": 0, "best_score": 0.0})
    state["run_count"] = int(state.get("run_count", 0)) + 1
    state["last_run"] = utcnow().isoformat()
    state["last_score"] = score
    state["last_report"] = str(report.relative_to(ROOT))

    champion = load_json(CHAMPION_PATH, {})
    if score >= float(state.get("best_score", 0.0)):
        state["best_score"] = score
        champion = {
            "score": score,
            "at": utcnow().isoformat(),
            "report": str(report.relative_to(ROOT)),
            "repo_maturity": audit["maturity_score"],
        }
        save_json(CHAMPION_PATH, champion)

    save_json(STATE_PATH, state)
    return state


def write_machine_artifact(intel: list[dict[str, Any]], audit: dict[str, Any], score: float) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utcnow().isoformat(),
        "score": score,
        "intel_count": len(intel),
        "audit": audit,
        "intel": intel[:50],
    }
    save_json(ARTIFACTS / "latest.json", payload)


def notify_slack(report: Path, score: float, queue_stats: dict[str, Any]) -> None:
    webhook = os.getenv("SLACK_RND_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    text = (
        f"Standment R&D daily run complete | score {score}/100 | "
        f"queue {queue_stats['queue_size']} (+{queue_stats['new_items']}) | report {report.name}"
    )
    body = json.dumps({"text": text}).encode("utf-8")
    try:
        req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as exc:
        append_failure("slack-report", str(exc))


def main() -> int:
    for directory in (REPORTS, MEMORY, ARTIFACTS):
        directory.mkdir(parents=True, exist_ok=True)

    intel, errors = collect_threat_intel()
    audit = run_repo_audit()
    queue_stats = update_research_queue(intel)
    score = portfolio_score(audit, len(intel), queue_stats)
    report = write_report(intel, errors, audit, queue_stats, score)
    state = update_memory(score, report, audit)
    write_machine_artifact(intel, audit, score)
    notify_slack(report, score, queue_stats)

    print(
        json.dumps(
            {
                "status": "ok",
                "report": str(report.relative_to(ROOT)),
                "score": score,
                "run_count": state["run_count"],
                **queue_stats,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
