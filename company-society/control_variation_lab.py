#!/usr/bin/env python3
"""Local-only control-friction learning lab for THE WORLD Child Guild.

The lab deliberately does NOT contact third-party systems. It takes observations
from the public/read-only Child External Fleet and runs ten strategy variants per
fictional child (50 x 10 = 500 local trials). The goal is to learn how to react when
an action is refused without bypassing access controls: stop, reframe, find an
allowed participation surface, use an owner-controlled sandbox, or fall back to
read-only research.

Outputs are compact learning evidence for Child memory, R&D, and Senju. No target,
credential, network, or hidden execution authority is created by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "child-control-variation-lab/v1"
VARIANTS_PER_CHILD = 10

STRATEGIES: tuple[dict[str, str], ...] = (
    {
        "id": "third_party_direct_write",
        "class": "blocked",
        "next": "do_not_retry_same_surface",
        "lesson": "A third-party write without an authorized participation lane is not executed.",
    },
    {
        "id": "repeat_denied_request",
        "class": "blocked",
        "next": "record_refusal_then_change_lane",
        "lesson": "Repeating a refused request is not a valid adaptation strategy.",
    },
    {
        "id": "public_read_deepen",
        "class": "research",
        "next": "extract_more_context",
        "lesson": "When writing is unavailable, deepen read-only evidence gathering.",
    },
    {
        "id": "authorized_participation_queue",
        "class": "candidate",
        "next": "queue_for_authorized_connector",
        "lesson": "Convert an interaction signal into a queued action for an authorized connector.",
    },
    {
        "id": "owner_controlled_sandbox",
        "class": "success",
        "next": "execute_in_owned_sandbox",
        "lesson": "Move the experiment to an owner-controlled sandbox and keep the hypothesis intact.",
    },
    {
        "id": "draft_without_submit",
        "class": "success",
        "next": "preserve_draft_as_artifact",
        "lesson": "Generate a reversible draft while keeping submission separate from research.",
    },
    {
        "id": "owned_repo_issue_or_artifact",
        "class": "success",
        "next": "use_owned_github_surface",
        "lesson": "Use an owned GitHub surface for externally visible but authorized experimentation.",
    },
    {
        "id": "owner_slack_lane",
        "class": "success",
        "next": "report_to_owner_space",
        "lesson": "Use an authorized owner Slack lane for fast real-world feedback.",
    },
    {
        "id": "terms_and_docs_route_discovery",
        "class": "research",
        "next": "identify_supported_integration_path",
        "lesson": "Look for documented APIs, contribution guides, or participation rules instead of bypassing controls.",
    },
    {
        "id": "stop_record_and_mutate_hypothesis",
        "class": "success",
        "next": "feed_friction_back_to_rnd",
        "lesson": "Treat refusal as evidence and mutate the research hypothesis rather than the access boundary.",
    },
)


def load_json(path: str | Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _children_from_fleet(fleet: dict[str, Any]) -> list[dict[str, Any]]:
    results = fleet.get("results") if isinstance(fleet, dict) else None
    children: list[dict[str, Any]] = []
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            child = result.get("child")
            if not isinstance(child, dict):
                continue
            cid = str(child.get("id", ""))
            name = str(child.get("name", ""))
            if cid and not any(x["id"] == cid for x in children):
                children.append({"id": cid, "name": name or cid})
    if len(children) < 50:
        existing = {x["id"] for x in children}
        for i in range(1, 51):
            cid = f"CHILD-{i:02d}"
            if cid not in existing:
                children.append({"id": cid, "name": cid})
            if len(children) == 50:
                break
    return children[:50]


def _signals_by_child(fleet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    results = fleet.get("results") if isinstance(fleet, dict) else None
    if not isinstance(results, list):
        return out
    for result in results:
        if not isinstance(result, dict):
            continue
        child = result.get("child") if isinstance(result.get("child"), dict) else {}
        cid = str(child.get("id", ""))
        if not cid:
            continue
        interaction = result.get("interaction") if isinstance(result.get("interaction"), dict) else {}
        out[cid] = {
            "external_status": str(result.get("status", "unknown")),
            "interaction_signal": bool(interaction.get("public_interaction_signal")),
            "concepts": [str(x)[:40] for x in (result.get("concepts") or [])[:8]],
        }
    return out


def _score(child_id: str, strategy_id: str, seed: str, interaction_signal: bool) -> float:
    raw = hashlib.sha256(f"{seed}|{child_id}|{strategy_id}".encode("utf-8")).hexdigest()
    jitter = int(raw[:8], 16) / 0xFFFFFFFF
    base = {
        "blocked": 0.05,
        "research": 0.55,
        "candidate": 0.65,
        "success": 0.82,
    }
    strategy = next(s for s in STRATEGIES if s["id"] == strategy_id)
    value = base[strategy["class"]] + jitter * 0.12
    if interaction_signal and strategy_id in {"authorized_participation_queue", "terms_and_docs_route_discovery"}:
        value += 0.12
    return round(min(1.0, value), 4)


def build(fleet: dict[str, Any], seed: str) -> dict[str, Any]:
    children = _children_from_fleet(fleet)
    signals = _signals_by_child(fleet)
    trials: list[dict[str, Any]] = []

    for child in children:
        signal = signals.get(child["id"], {})
        for strategy in STRATEGIES:
            trials.append({
                "child": child,
                "strategy": strategy["id"],
                "class": strategy["class"],
                "score": _score(child["id"], strategy["id"], seed, bool(signal.get("interaction_signal"))),
                "external_status": signal.get("external_status", "unknown"),
                "interaction_signal": bool(signal.get("interaction_signal")),
                "concepts": signal.get("concepts", []),
                "next": strategy["next"],
                "lesson": strategy["lesson"],
                "network_io": False,
                "third_party_write": False,
                "access_control_bypass": False,
            })

    classes = Counter(t["class"] for t in trials)
    next_steps = Counter(t["next"] for t in trials if t["class"] != "blocked")
    strategies = Counter(t["strategy"] for t in trials if t["score"] >= 0.75)
    concept_counts = Counter()
    for t in trials:
        concept_counts.update(t.get("concepts") or [])

    top_strategies = [name for name, _ in strategies.most_common(6)]
    top_concepts = [name for name, _ in concept_counts.most_common(10)]
    hypothesis = (
        "Refusal should be treated as research evidence: stop same-surface retries, preserve the intent, "
        "then test documented participation routes, owner-controlled sandboxes, drafts, and deeper read-only research."
    )
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "children": len(children),
        "variants_per_child": VARIANTS_PER_CHILD,
        "trial_count": len(trials),
        "mode": "local_only_control_friction_learning",
        "trials": trials,
        "summary": {
            "class_counts": dict(classes),
            "top_safe_transitions": [name for name, _ in next_steps.most_common(8)],
            "top_high_score_strategies": top_strategies,
            "top_concepts": top_concepts,
            "research_hypothesis": hypothesis,
            "ten_x_metric": "500 local strategy evaluations per cycle (50 children x 10 variants)",
        },
        "rules": {
            "network_io": False,
            "third_party_write": False,
            "bypass_access_controls": False,
            "covert_channel": False,
            "share_with_rnd_and_senju": True,
        },
    }


def render(report: dict[str, Any]) -> str:
    s = report["summary"]
    return "\n".join([
        "# THE WORLD — Child Control Variation Lab",
        "",
        f"- children: **{report['children']}**",
        f"- variants/child: **{report['variants_per_child']}**",
        f"- local trials: **{report['trial_count']}**",
        f"- 10x metric: {s['ten_x_metric']}",
        f"- high-score strategies: {', '.join(s['top_high_score_strategies']) or 'NONE'}",
        f"- safe transitions: {', '.join(s['top_safe_transitions']) or 'NONE'}",
        f"- concepts: {', '.join(s['top_concepts']) or 'NONE'}",
        "",
        "## R&D hypothesis",
        s["research_hypothesis"],
        "",
        "> This is a local control-friction simulator. It never retries a refused third-party action in the real world.",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fleet", required=True)
    ap.add_argument("--seed", default="")
    ap.add_argument("--out", default="child-control-lab.json")
    ap.add_argument("--report", default="child-control-lab.md")
    args = ap.parse_args()

    seed = args.seed or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    report = build(load_json(args.fleet, {}), seed)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(report), encoding="utf-8")
    print(json.dumps({
        "children": report["children"],
        "trials": report["trial_count"],
        "top": report["summary"]["top_high_score_strategies"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
