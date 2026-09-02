"""Convert authorized pentest observations into offense-first research campaigns.

The input is evidence already collected by ``senju.pentest_fabric``. This adapter
never contacts the observed target and never emits exploit payloads. It turns measured
findings into synthetic attack surfaces so RED can decide what to research next inside
Arena / authorized-lab workflows instead of handing every finding directly to BLUE.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .offense import OffenseDirector, OffensiveMemory
from .targets.base import Surface

SCHEMA = "senju-pentest-to-red/v1"

_SEVERITY_WEIGHT = {
    "critical": 1.00,
    "high": 0.92,
    "medium": 0.74,
    "low": 0.52,
    "info": 0.34,
}

_FINDING_TO_VULN = {
    "csp-missing": "xss",
    "xcto-missing": "xss",
    "referrer-policy-missing": "secrets_exposure",
    "hsts-missing": "misconfig",
    "cookie-secure-missing": "auth_bypass",
    "cookie-httponly-missing": "auth_bypass",
    "cookie-samesite-missing": "csrf",
    "cors-wildcard-credentials": "csrf",
    "cors-origin-reflection": "csrf",
    "dangerous-methods-advertised": "misconfig",
    "unknown-route-success": "auth_bypass",
    "unknown-route-5xx": "misconfig",
    "head-5xx": "misconfig",
    "banner-server": "secrets_exposure",
    "banner-x-powered-by": "secrets_exposure",
}

_BASELINE_HUNT = (
    ("novel-auth-route", "auth_bypass", 0.82),
    ("novel-object-boundary", "idor", 0.80),
    ("novel-server-fetch", "ssrf", 0.86),
    ("novel-race-window", "race_condition", 0.78),
    ("novel-config-edge", "misconfig", 0.76),
)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return slug[:80] or "authorized-observation"


def _severity(raw: Any) -> str:
    value = str(raw or "info").lower().strip()
    return value if value in _SEVERITY_WEIGHT else "info"


def _vuln_for_key(key: str) -> str:
    if key in _FINDING_TO_VULN:
        return _FINDING_TO_VULN[key]
    if key.startswith("cors-"):
        return "csrf"
    if key.startswith("cookie-"):
        return "auth_bypass"
    if key.startswith("banner-"):
        return "secrets_exposure"
    if "route" in key or "auth" in key:
        return "auth_bypass"
    return "misconfig"


@dataclass
class EvidenceTarget:
    ref: str
    _surfaces: list[Surface]

    def surfaces(self) -> list[Surface]:
        return [
            Surface(
                name=s.name,
                vuln_class=s.vuln_class,
                difficulty=s.difficulty,
                mitigated=s.mitigated,
                monitored=s.monitored,
            )
            for s in self._surfaces
        ]


@dataclass
class EvidenceRedGenome:
    focus: dict[str, float] = field(default_factory=dict)
    skill: float = 0.72
    stealth: float = 0.66
    aggression: float = 0.82
    recon_depth: float = 0.86
    chain_synergy: float = 0.78
    evasion_adapt: float = 0.74


def report_to_target(report: Mapping[str, Any]) -> tuple[EvidenceTarget, EvidenceRedGenome, list[dict[str, Any]]]:
    """Turn measured findings into synthetic RED pressure surfaces."""
    if report.get("schema") != "senju-authorized-pentest-report/v1":
        raise ValueError("unsupported pentest report schema")

    findings = report.get("findings") or []
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")

    scope_id = _safe_slug(str(report.get("scope_id") or "unknown-scope"))
    surfaces: list[Surface] = []
    focus_accumulator: dict[str, list[float]] = {}
    source_map: list[dict[str, Any]] = []

    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, Mapping):
            continue
        key = str(finding.get("key") or f"finding-{index}").strip()
        sev = _severity(finding.get("severity"))
        weight = _SEVERITY_WEIGHT[sev]
        vuln = _vuln_for_key(key)

        # A measured weakness is an attack-research clue, not proof of exploitability.
        # Higher severity raises RED focus; difficulty stays non-trivial so the Arena
        # must still earn a breakthrough instead of treating a finding as a capture.
        difficulty = round(0.48 + 0.32 * (1.0 - weight), 3)
        surfaces.append(
            Surface(
                name=f"finding-{index}-{_safe_slug(key)}",
                vuln_class=vuln,
                difficulty=difficulty,
                mitigated=False,
                monitored=sev in {"critical", "high"},
            )
        )
        focus_accumulator.setdefault(vuln, []).append(weight)
        source_map.append({
            "finding_key": key,
            "severity": sev,
            "research_vuln_class": vuln,
            "interpretation": "measured-observation-to-synthetic-red-pressure",
        })

    if not surfaces:
        # No finding is not the end of RED research. Generate difficult synthetic
        # novelty-hunt surfaces without claiming that the observed target has them.
        for name, vuln, difficulty in _BASELINE_HUNT:
            surfaces.append(Surface(name=name, vuln_class=vuln, difficulty=difficulty, mitigated=True, monitored=True))
            focus_accumulator.setdefault(vuln, []).append(0.66)
            source_map.append({
                "finding_key": None,
                "severity": "none",
                "research_vuln_class": vuln,
                "interpretation": "no-known-finding-novelty-hunt",
            })

    focus = {
        vuln: round(min(1.0, max(values) + 0.04 * (len(values) - 1)), 3)
        for vuln, values in focus_accumulator.items()
    }
    target = EvidenceTarget(ref=f"sim://pentest-intel/{scope_id}", _surfaces=surfaces)
    return target, EvidenceRedGenome(focus=focus), source_map


def _run_report(report: Mapping[str, Any], *, cycles: int, seed: int, max_steps: int) -> dict[str, Any]:
    target, genome, source_map = report_to_target(report)
    director = OffenseDirector(max_steps=max_steps)
    memory = OffensiveMemory()
    campaigns: list[dict[str, Any]] = []

    for index in range(max(1, int(cycles))):
        campaign = director.plan(target, genome, memory)
        outcome = director.execute(campaign, target, genome, memory, seed=seed + index)
        campaigns.append({
            "campaign": {
                "campaign_id": campaign.campaign_id,
                "target_ref": campaign.target_ref,
                "objective": campaign.objective,
                "doctrine": campaign.doctrine,
                "steps": [asdict(step) for step in campaign.steps],
            },
            "outcome": {
                "red_score": outcome.red_score,
                "won": outcome.won,
                "captures": list(outcome.captures),
                "detections": list(outcome.detections),
                "lessons": list(outcome.lessons),
                "next_pressure": list(outcome.next_pressure),
            },
        })

    pressure: list[tuple[int, float, str]] = []
    for vuln, state in memory.by_class.items():
        pressure.append((state.consecutive_failures, state.success_rate, vuln))
    pressure.sort(key=lambda item: (-item[0], item[1], item[2]))

    return {
        "scope_id": report.get("scope_id"),
        "source_report_schema": report.get("schema"),
        "source_target": report.get("target"),
        "measured_findings": len(report.get("findings") or []),
        "synthetic_target_ref": target.ref,
        "source_map": source_map,
        "red_focus": genome.focus,
        "campaigns": campaigns,
        "memory": memory.to_dict(),
        "priority_next": [vuln for _, _, vuln in pressure[:8]],
    }


def build_bundle(reports: Iterable[Mapping[str, Any]], *, cycles: int = 12, seed: int = 20260830, max_steps: int = 6) -> dict[str, Any]:
    items = []
    for index, report in enumerate(reports):
        items.append(_run_report(report, cycles=cycles, seed=seed + index * 1000, max_steps=max_steps))
    if not items:
        raise ValueError("at least one pentest report is required")

    priorities: list[str] = []
    for item in items:
        for vuln in item["priority_next"]:
            if vuln not in priorities:
                priorities.append(vuln)

    return {
        "schema": SCHEMA,
        "doctrine": "REAL_OBSERVATION_TO_RED_RESEARCH",
        "network_io": False,
        "exploit_payloads_emitted": False,
        "source_authority_widened": False,
        "source_reports": len(items),
        "cycles_per_report": max(1, int(cycles)),
        "priority_next": priorities[:12],
        "reports": items,
    }


def load_reports(paths: Sequence[str | Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in paths:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"report must be a JSON object: {path}")
        reports.append(value)
    return reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn authorized pentest evidence into RED research campaigns")
    parser.add_argument("--report", action="append", required=True, help="authorized pentest report JSON; repeatable")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args(argv)

    bundle = build_bundle(
        load_reports(args.report),
        cycles=args.cycles,
        seed=args.seed,
        max_steps=args.max_steps,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "SENJU_PENTEST_TO_RED_VERIFIED "
        f"reports={bundle['source_reports']} priorities={','.join(bundle['priority_next'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
