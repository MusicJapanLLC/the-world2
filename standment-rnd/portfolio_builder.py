#!/usr/bin/env python3
"""Build a human-readable Standment security portfolio from R&D artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "STANDMENT_SECURITY_PORTFOLIO.md"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def main() -> int:
    state = load(HERE / "memory" / "state.json", {})
    champion = load(HERE / "memory" / "champion.json", {})
    latest = load(HERE / "artifacts" / "latest.json", {})
    registry = load(HERE / "agent_registry.json", {"agents": []})
    queue = load(HERE / "research_queue.json", {"items": []})

    audit = latest.get("audit", {})
    controls = audit.get("controls", {})
    queue_items = sorted(queue.get("items", []), key=lambda x: int(x.get("priority", 0)), reverse=True)
    agents = registry.get("agents", [])
    report_paths = sorted((HERE / "reports").glob("*.md"), reverse=True)[:7] if (HERE / "reports").exists() else []

    lines = [
        "# Standment Security Engineering Portfolio",
        "",
        "> Defensive security R&D, automation, software assurance and evidence-driven improvement.",
        "",
        "## Current R&D system",
        "",
        "Standment R&D runs as a repeatable defensive research loop connected to The world automation layer. It collects public threat intelligence, audits owned code and CI controls, maintains research memory, scores each run, and continuously regenerates this portfolio from evidence.",
        "",
        "### Operating model",
        "",
        "`Scout -> Hypothesis -> Defensive Experiment -> Evaluator -> Memory -> Portfolio -> Next Research Queue`",
        "",
        "Changes to real code are promoted through `branch -> test -> review -> merge`; research is limited to public information and owned/explicitly authorized environments.",
        "",
        "## Live engineering metrics",
        "",
        f"- Autonomous R&D runs recorded: **{state.get('run_count', 0)}**",
        f"- Latest R&D score: **{state.get('last_score', 'n/a')}**",
        f"- Best recorded score: **{state.get('best_score', champion.get('score', 'n/a'))}**",
        f"- Repository defensive maturity: **{audit.get('maturity_score', 'n/a')}**",
        f"- Public defensive signals in latest run: **{latest.get('intel_count', 0)}**",
        f"- Active research queue: **{len(queue_items)}**",
        f"- Registered R&D agent roles: **{len(agents)}**",
        "",
        "## Defensive capabilities demonstrated",
        "",
        "- Automated vulnerability-intelligence ingestion from public defensive sources",
        "- Repository and CI security-control inventory",
        "- Lightweight secret-hygiene scanning without exposing matched values",
        "- Code compilation / integrity checks inside CI",
        "- Failure memory and champion-score tracking",
        "- Bounded autonomous research backlog generation",
        "- Scheduled evidence-based R&D reporting",
        "- Portfolio generation directly from machine-produced artifacts",
        "- Existing CodeQL / dependency / self-heal / control-plane integration awareness",
        "",
        "## Current security controls",
        "",
    ]

    if controls:
        for name, enabled in controls.items():
            lines.append(f"- {'✅' if enabled else '⬜'} `{name}`")
    else:
        lines.append("- Awaiting first autonomous R&D run")

    lines.extend(["", "## R&D agent society", ""])
    for agent in agents:
        lines.append(f"- **{agent.get('id')} / {agent.get('role')}** — {agent.get('mission')}")

    lines.extend(["", "## Highest-priority research queue", ""])
    if queue_items:
        for item in queue_items[:12]:
            lines.append(
                f"- **{item.get('id')}** [{item.get('priority', 0)}] {item.get('title')} — `{item.get('scope', 'internal')}`"
            )
    else:
        lines.append("- Queue empty")

    lines.extend(["", "## Recent R&D evidence", ""])
    if report_paths:
        for report in report_paths:
            rel = report.relative_to(ROOT).as_posix()
            lines.append(f"- [{report.stem}]({rel})")
    else:
        lines.append("- First daily report will appear after the scheduled workflow runs")

    lines.extend(
        [
            "",
            "## Engineering principle",
            "",
            "The portfolio is not a claim that a scanner or agent is infallible. Each result is treated as an experiment with evidence, limitations and a repeatable path to improvement. Failed experiments are retained as memory instead of being hidden.",
            "",
            "## Research boundary",
            "",
            "Standment security research is defensive: passive public research plus owned or explicitly authorized systems and sandboxes. Unauthorized exploitation, credential bypass, persistence, destructive testing and third-party modification are out of scope.",
            "",
            "---",
            "Generated by `standment-rnd/portfolio_builder.py` from current R&D state.",
        ]
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
