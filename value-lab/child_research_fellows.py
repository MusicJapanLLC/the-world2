#!/usr/bin/env python3
"""Generate bounded Child Guild research sparks for the R&D / Senju loop.

The Child Guild is a fictional AI-persona society. Fellows may challenge assumptions
and suggest one alternate simulator research focus. They may also receive an abstract
R&D seed from Outside World Scout, but external URLs/hosts/targets never enter the
child research artifact or Senju directive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

ALLOWED_FOCUS = ("robustness", "learning", "balance", "efficiency")
FORBIDDEN_KEYS = {
    "target", "url", "host", "network", "scope", "permission", "secret",
    "credential", "exploit", "victim", "workflow", "endpoint",
}


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def choose_research(queue: dict[str, Any]) -> dict[str, Any]:
    rows = [x for x in (queue.get("active") or []) if isinstance(x, dict)]
    if not rows:
        return {"research_id": "RND-CHILD-DEFAULT", "title": "Default curiosity probe", "focus": "robustness", "priority": 0}
    rows.sort(key=lambda x: (int(x.get("priority", 0) or 0), str(x.get("research_id", ""))), reverse=True)
    return rows[0]


def extract_holdout(senju: dict[str, Any]) -> dict[str, Any]:
    shadow = senju.get("shadow_champion") or {}
    holdout = shadow.get("holdout") if isinstance(shadow, dict) else {}
    return holdout if isinstance(holdout, dict) else {}


def sanitize_outside_seed(raw: dict[str, Any]) -> dict[str, str]:
    """Keep only non-locating abstract inspiration; deliberately discard URL/source IDs."""
    if not raw or raw.get("schema") != "outside-world-rnd-seed/v1" or raw.get("eligible") is not True:
        return {}
    directive = raw.get("candidate_directive") if isinstance(raw.get("candidate_directive"), dict) else {}
    focus = str(directive.get("focus", ""))
    if focus not in ALLOWED_FOCUS:
        return {}
    source = raw.get("source_evidence") if isinstance(raw.get("source_evidence"), dict) else {}
    title = str(source.get("title", "external discovery"))[:160]
    category = str(source.get("category", "technical"))[:40]
    hypothesis = str(directive.get("hypothesis", ""))[:300]
    return {"focus": focus, "title": title, "category": category, "hypothesis": hypothesis}


def choose_challenge_focus(research: dict[str, Any], senju: dict[str, Any], outside_seed: dict[str, Any] | None = None) -> tuple[str, str]:
    holdout = extract_holdout(senju)
    balance = float(holdout.get("worst_balance", 1.0) or 1.0)
    learning = float(holdout.get("worst_learning_signal", 1.0) or 1.0)
    stdev = float(holdout.get("score_stdev", 0.0) or 0.0)

    # Measured weakness beats novelty. Children may challenge assumptions, not ignore evidence.
    if balance < 0.60:
        return "balance", f"worst_balance={balance:.4f} is the softest visible edge"
    if learning < 0.80:
        return "learning", f"worst_learning_signal={learning:.4f} leaves learning headroom"
    if stdev > 25.0:
        return "robustness", f"score_stdev={stdev:.4f} still looks noisy"

    current = str(research.get("focus", "robustness"))
    outside = sanitize_outside_seed(outside_seed or {})
    if outside and outside["focus"] != current:
        return outside["focus"], f"Outside World abstract pattern ({outside['category']}): {outside['title']}"

    alternatives = [x for x in ALLOWED_FOCUS if x != current]
    return ("efficiency" if "efficiency" in alternatives else alternatives[0]), "baseline looks healthy enough to challenge efficiency instead of repeating the same question"


def pick_fellows(registry: dict[str, Any], seed: str, research_id: str, count: int = 3) -> list[dict[str, str]]:
    members = [m for m in (registry.get("members") or []) if isinstance(m, dict) and m.get("id") and m.get("name")]
    if len(members) < count:
        raise ValueError("not enough Child Guild members")
    digest = hashlib.sha256(f"{seed}:{research_id}".encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    picked = rng.sample(members, count)
    roles = ("WHY-KID", "CHAOS-INVENTOR", "SAFETY-GOBLIN")
    return [{"id": str(m["id"]), "name": str(m["name"]), "role": roles[i]} for i, m in enumerate(picked)]


def build_sparks(
    registry: dict[str, Any],
    queue: dict[str, Any],
    senju: dict[str, Any],
    seed: str,
    outside_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if registry.get("shared_rules", {}).get("credential_or_secret_access") is not False:
        raise ValueError("Child Guild secret-access boundary is not locked")
    research = choose_research(queue)
    research_id = str(research.get("research_id", "RND-CHILD-DEFAULT"))
    fellows = pick_fellows(registry, seed, research_id)
    outside = sanitize_outside_seed(outside_seed or {})
    focus, reason = choose_challenge_focus(research, senju, outside_seed)
    current_focus = str(research.get("focus", "robustness"))

    outside_question = (
        f" 外で見つけた『{outside['title']}』の場所やURLは捨てて、考え方だけ借りるなら何が使える？"
        if outside else ""
    )
    questions = [
        f"{fellows[0]['name']}: そもそも『{current_focus}を強くする』以外の前提を疑ったら何が見える？{outside_question}",
        f"{fellows[1]['name']}: 次の1回だけ {focus} を主役にしたら、今のChampionの弱点は増える？減る？",
        f"{fellows[2]['name']}: 一番いい平均値じゃなく、一番イヤなseedで壊れないことをどう証明する？",
    ]
    result = {
        "schema": "child-rnd-sparks/v1",
        "fictional_personas": True,
        "research_id": research_id,
        "research_title": str(research.get("title", ""))[:300],
        "current_focus": current_focus,
        "challenge_focus": focus,
        "candidate_bonus": 1,
        "fellows": fellows,
        "questions": questions,
        "reason": reason,
        "guardrail": "ideas only; bounded simulator research focus; no external target/network/permission/secret surface",
    }
    lowered = json.dumps(result, ensure_ascii=False).lower()
    for key in FORBIDDEN_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError(f"forbidden child research key: {key}")
    # Explicit invariant: raw outside location/scope must never be copied into the spark.
    if outside_seed:
        raw_source = outside_seed.get("source_evidence") if isinstance(outside_seed.get("source_evidence"), dict) else {}
        raw_url = str(raw_source.get("url", ""))
        if raw_url and raw_url in json.dumps(result, ensure_ascii=False):
            raise ValueError("outside URL leaked into child research spark")
    if result["challenge_focus"] not in ALLOWED_FOCUS:
        raise ValueError("unsupported challenge focus")
    return result


def render(sparks: dict[str, Any]) -> str:
    lines = [
        "# Child Guild — Research Fellows",
        "",
        f"- research: **{sparks['research_id']}** — {sparks['research_title']}",
        f"- current focus: **{sparks['current_focus']}**",
        f"- child challenge focus: **{sparks['challenge_focus']}**",
        f"- reason: {sparks['reason']}",
        "- fellows: " + ", ".join(f"{x['name']}({x['role']})" for x in sparks["fellows"]),
        "",
        "## Questions",
        *[f"- {q}" for q in sparks["questions"]],
        "",
        "> 子供の役目は前提を揺らすこと。実行境界・安全境界を揺らすことではない。外界からは抽象パターンだけを持ち帰る。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="company-society/child_guild.json")
    ap.add_argument("--queue", default="value-lab/research_queue.json")
    ap.add_argument("--senju", default="senju/state/last-evolution-summary.json")
    ap.add_argument("--outside-seed", default=None)
    ap.add_argument("--seed", default="child-rnd")
    ap.add_argument("--out", default="child-research-sparks.json")
    ap.add_argument("--report", default="child-research-sparks.md")
    args = ap.parse_args()

    sparks = build_sparks(
        load_json(args.registry), load_json(args.queue), load_json(args.senju), args.seed,
        load_json(args.outside_seed),
    )
    Path(args.out).write_text(json.dumps(sparks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(render(sparks), encoding="utf-8")
    print(json.dumps({"research_id": sparks["research_id"], "challenge_focus": sparks["challenge_focus"], "fellows": [x["name"] for x in sparks["fellows"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
