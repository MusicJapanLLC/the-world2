#!/usr/bin/env python3
"""Passive defensive-intelligence collector for Standment Security R&D.

The collector reads public vulnerability intelligence and the owned repository's
security controls, then emits a bounded research seed. It never probes, exploits,
authenticates to, or modifies third-party systems.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CISA_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
GITHUB_ADVISORIES = "https://api.github.com/advisories?per_page=25&sort=published&direction=desc"

OWNED_CONTROL_FILES = {
    "security_standard": "security/STANDMENT_SECURITY_STANDARD.md",
    "company_baseline": "standment-security/SECURITY_BASELINE.md",
    "security_guard": ".github/workflows/security-guard.yml",
    "security_gate": ".github/workflows/standment-security-gate.yml",
    "codeql": ".github/workflows/codeql.yml",
    "dependency_review": ".github/workflows/dependency-review.yml",
    "dependency_audit": ".github/workflows/dependency-audit.yml",
    "portfolio_rnd": ".github/workflows/standment-security-portfolio-rnd.yml",
    "workflow_policy": "automation/security/workflow_policy.py",
    "senju_bridge": "value-lab/senju_bridge.py",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Standment-Defensive-RD/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_public_intel() -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        kev = fetch_json(CISA_KEV)
        rows = kev.get("vulnerabilities", []) if isinstance(kev, dict) else []
        rows = sorted(rows, key=lambda x: str(x.get("dateAdded", "")), reverse=True)[:20]
        for item in rows:
            findings.append(
                {
                    "source": "CISA KEV",
                    "id": str(item.get("cveID", "unknown")),
                    "date": str(item.get("dateAdded", "")),
                    "vendor": str(item.get("vendorProject", "")),
                    "product": str(item.get("product", "")),
                    "defensive_action": str(item.get("requiredAction", ""))[:500],
                }
            )
    except Exception as exc:  # External input failure must degrade, not kill the full R&D loop.
        errors.append(f"CISA KEV unavailable: {type(exc).__name__}")

    try:
        advisories = fetch_json(GITHUB_ADVISORIES)
        if isinstance(advisories, list):
            for item in advisories[:20]:
                findings.append(
                    {
                        "source": "GitHub Advisory Database",
                        "id": str(item.get("cve_id") or item.get("ghsa_id") or "unknown"),
                        "date": str(item.get("published_at", "")),
                        "severity": str(item.get("severity", "unknown")),
                        "summary": str(item.get("summary", ""))[:500],
                    }
                )
    except Exception as exc:
        errors.append(f"GitHub Advisory Database unavailable: {type(exc).__name__}")

    findings.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    return findings[:40], errors


def audit_owned_controls(root: Path) -> dict[str, Any]:
    controls = {name: (root / path).exists() for name, path in OWNED_CONTROL_FILES.items()}
    present = sum(1 for enabled in controls.values() if enabled)
    total = len(controls)
    missing = [OWNED_CONTROL_FILES[name] for name, enabled in controls.items() if not enabled]
    return {
        "controls": controls,
        "present": present,
        "total": total,
        "coverage": round(present / total, 3) if total else 0.0,
        "missing": missing,
    }


def build_research_seed(intel: list[dict[str, Any]], audit: dict[str, Any], stamp: datetime) -> dict[str, Any]:
    missing = list(audit.get("missing") or [])
    kev = next((x for x in intel if x.get("source") == "CISA KEV"), None)

    if missing:
        problem = "Owned defensive-control evidence is incomplete: " + ", ".join(missing[:5])
        hypothesis = (
            "Closing the highest-value owned control-evidence gap and retesting it will improve "
            "Standment's reproducibility and customer-inspectable security evidence."
        )
        focus = "robustness"
    elif kev:
        problem = (
            f"Fresh exploited-vulnerability signal {kev.get('id')} requires a bounded exposure-review method "
            "for owned assets without probing third parties."
        )
        hypothesis = (
            "Mapping fresh exploited-vulnerability intelligence to software inventory, dependency evidence, "
            "mitigations and retest criteria will shorten the path from public signal to defensible action."
        )
        focus = "learning"
    else:
        problem = "No fresh external signal was available; improve repeatability of the owned defensive evidence cycle."
        hypothesis = (
            "Re-running the owned control audit with explicit counterevidence and reproducibility checks will "
            "make the portfolio stronger even when external intelligence is quiet."
        )
        focus = "efficiency"

    return {
        "research_id": f"RND-STANDMENT-DEFENSIVE-INTEL-{stamp.strftime('%Y%m%d')}",
        "title": "Standment daily defensive-intelligence to evidence cycle",
        "problem": problem[:700],
        "hypothesis": hypothesis[:600],
        "focus": focus,
        "priority": 3600,
        "candidate_count": 9,
        "success": {
            "safe": True,
            "stable": True,
            "holdout_required": True,
            "worst_score_positive": True,
            "worst_balance_min": 0.35,
            "worst_learning_min": 0.05,
            "score_stdev_max": 35.0,
        },
        "commercial_bridge": (
            "Use this research only to improve defensive evidence quality and response repeatability. "
            "Technical evidence does not establish buyer demand, contracts, payments or revenue."
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    audit = payload["owned_control_audit"]
    intel = payload["public_intel"]
    lines = [
        "# Standment Security — Daily Defensive Intelligence",
        "",
        f"- generated: {payload['generated_at']}",
        f"- public defensive signals collected: **{len(intel)}**",
        f"- owned security-control evidence: **{audit['present']}/{audit['total']} ({audit['coverage']:.0%})**",
        f"- degraded public sources: **{len(payload['source_errors'])}**",
        "",
        "## Fresh defensive signals",
    ]
    if not intel:
        lines.append("- No public intelligence was available in this run.")
    for item in intel[:12]:
        detail = item.get("summary") or item.get("defensive_action") or ""
        product = " ".join(x for x in [str(item.get("vendor", "")), str(item.get("product", ""))] if x)
        lines.append(f"- **{item.get('id')}** {product} — {str(detail)[:240]}".rstrip())

    lines.extend(["", "## Owned defensive-control evidence"])
    for name, enabled in audit["controls"].items():
        lines.append(f"- {'✅' if enabled else '⬜'} `{name}`")

    lines.extend(
        [
            "",
            "## Next bounded R&D seed",
            f"- {payload['research_seed']['research_id']}",
            f"- focus: **{payload['research_seed']['focus']}**",
            f"- problem: {payload['research_seed']['problem']}",
            f"- hypothesis: {payload['research_seed']['hypothesis']}",
            "",
            "## Boundary",
            "Public information plus owned/explicitly authorized environments only. No unauthorized probing, exploitation, credential bypass, persistence, destructive testing or third-party modification.",
        ]
    )
    if payload["source_errors"]:
        lines.extend(["", "## Degraded inputs"])
        lines.extend(f"- {x}" for x in payload["source_errors"])
    return "\n".join(lines) + "\n"


def run(root: Path, out: Path, *, public_intel: list[dict[str, Any]] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    stamp = now()
    if public_intel is None:
        public_intel, source_errors = collect_public_intel()
    else:
        source_errors = list(errors or [])
    audit = audit_owned_controls(root)
    seed = build_research_seed(public_intel, audit, stamp)
    payload = {
        "schema": "standment-defensive-intel/v1",
        "generated_at": stamp.isoformat(timespec="seconds"),
        "boundary": "passive-public-and-owned-authorized-only",
        "public_intel": public_intel,
        "source_errors": source_errors,
        "owned_control_audit": audit,
        "research_seed": seed,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "intel.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "intel.md").write_text(render_markdown(payload), encoding="utf-8")
    (out / "research-seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reports/standment-security-rnd")
    args = ap.parse_args()
    payload = run(Path(args.root).resolve(), Path(args.out))
    print(
        json.dumps(
            {
                "intel": len(payload["public_intel"]),
                "control_coverage": payload["owned_control_audit"]["coverage"],
                "research_id": payload["research_seed"]["research_id"],
                "focus": payload["research_seed"]["focus"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
