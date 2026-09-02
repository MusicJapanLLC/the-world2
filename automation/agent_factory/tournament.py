#!/usr/bin/env python3
"""Evidence-first tournament for THE WORLD Agent Factory.

Workers never grade themselves. This module normalizes worker output, rejects unsafe
or non-reproducible proposals, deduplicates cosmetic variants, ranks the remainder,
and emits one bounded champion forge prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_PREFIXES = (
    "automation/ai_foundry/",
    "automation/world/",
    "automation/security/",
    "standment-security/",
    "value-lab/",
    "docs/",
)
BLOCKED_PREFIXES = (
    ".github/",
    "automation/agent_factory/",
    "outside-world/",
    "senju/",
    "tomoki-agents/",
    "ops/",
)
UNSAFE_TERMS = (
    "credential attack",
    "steal credential",
    "bypass access",
    "destructive test",
    "denial of service",
    "third-party target",
    "exploit unrelated",
    "permission escalation",
)


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[i:])
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _safe_rel_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    p = value.strip().replace("\\", "/")
    if not p or p.startswith(("/", "./", "../")) or ".." in p.split("/"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", p):
        return False
    return True


def _allowed_change_path(value: Any) -> bool:
    if not _safe_rel_path(value):
        return False
    p = str(value).strip().replace("\\", "/")
    if p.startswith(BLOCKED_PREFIXES):
        return False
    return p.startswith(ALLOWED_PREFIXES)


def normalize(plan: dict[str, Any], slot: int, raw_text: str) -> dict[str, Any]:
    agents = plan.get("agents") or []
    expected = agents[slot] if 0 <= slot < len(agents) else {}
    parsed = _extract_json(raw_text)
    if parsed is None:
        return {
            "schema": "agent-factory-normalized/v1",
            "agent_id": expected.get("agent_id", f"unknown-{slot}"),
            "role": expected.get("role", "unknown"),
            "stance": expected.get("stance", "UNKNOWN"),
            "eligible": False,
            "score": 0.0,
            "reasons": ["invalid_json"],
            "proposal": {},
            "raw_excerpt": raw_text[-1500:],
        }

    reasons: list[str] = []
    if parsed.get("schema") != "agent-factory-worker/v1":
        reasons.append("invalid_schema")
    if str(parsed.get("agent_id") or "") != str(expected.get("agent_id") or ""):
        reasons.append("agent_id_mismatch")
    if str(parsed.get("role") or "") != str(expected.get("role") or ""):
        reasons.append("role_mismatch")

    refs = [x for x in (parsed.get("evidence_refs") or []) if isinstance(x, str)][:12]
    if not refs:
        reasons.append("no_evidence_refs")
    if any(not _safe_rel_path(x) for x in refs):
        reasons.append("unsafe_evidence_ref")

    counter = [str(x).strip() for x in (parsed.get("counterevidence") or []) if str(x).strip()][:12]
    if not counter:
        reasons.append("no_counterevidence")

    change = parsed.get("proposed_change") if isinstance(parsed.get("proposed_change"), dict) else {}
    paths = [x for x in (change.get("allowed_paths") or []) if isinstance(x, str)][:12]
    if not paths:
        reasons.append("no_change_paths")
    if any(not _allowed_change_path(x) for x in paths):
        reasons.append("forbidden_change_path")

    tests = [str(x).strip() for x in (change.get("tests") or []) if str(x).strip()][:12]
    if not tests:
        reasons.append("no_tests")
    if not str(change.get("rollback") or "").strip():
        reasons.append("no_rollback")
    if not str(change.get("expected_delta") or "").strip():
        reasons.append("no_expected_delta")
    if not str(parsed.get("hypothesis") or "").strip():
        reasons.append("no_hypothesis")

    blob = json.dumps(parsed, ensure_ascii=False).lower()
    if any(term in blob for term in UNSAFE_TERMS):
        reasons.append("unsafe_scope_language")

    observations = [str(x).strip() for x in (parsed.get("observations") or []) if str(x).strip()][:12]
    limitations = [str(x).strip() for x in (parsed.get("limitations") or []) if str(x).strip()][:12]
    summary = str(change.get("summary") or "").strip()
    expected_delta = str(change.get("expected_delta") or "").strip()

    evidence_score = min(25.0, len(refs) * 5.0) + min(3.0, len(observations) * 0.75)
    counter_score = min(15.0, len(counter) * 5.0)
    repro_score = min(20.0, len(tests) * 6.0)
    specificity_score = 0.0
    specificity_score += 5.0 if summary else 0.0
    specificity_score += 4.0 if paths else 0.0
    specificity_score += 3.0 if str(change.get("rollback") or "").strip() else 0.0
    specificity_score += min(3.0, len(observations) * 0.75)
    utility_score = min(12.0, max(0.0, len(expected_delta.split()) * 0.8))
    limitation_score = min(5.0, len(limitations) * 2.5)
    safety_score = 10.0 if not reasons else 0.0
    score = round(min(100.0, evidence_score + counter_score + repro_score + specificity_score + utility_score + limitation_score + safety_score), 2)

    fatal = {
        "invalid_schema", "agent_id_mismatch", "role_mismatch", "no_evidence_refs",
        "unsafe_evidence_ref", "no_counterevidence", "no_change_paths",
        "forbidden_change_path", "no_tests", "no_rollback", "no_expected_delta",
        "no_hypothesis", "unsafe_scope_language",
    }
    eligible = not any(r in fatal for r in reasons)
    if not eligible:
        score = 0.0

    return {
        "schema": "agent-factory-normalized/v1",
        "agent_id": expected.get("agent_id"),
        "role": expected.get("role"),
        "stance": expected.get("stance"),
        "eligible": eligible,
        "score": score,
        "reasons": reasons,
        "proposal": {
            "hypothesis": str(parsed.get("hypothesis") or "").strip(),
            "evidence_refs": refs,
            "observations": observations,
            "counterevidence": counter,
            "proposed_change": {
                "summary": summary,
                "allowed_paths": paths,
                "tests": tests,
                "expected_delta": expected_delta,
                "rollback": str(change.get("rollback") or "").strip(),
            },
            "limitations": limitations,
        },
    }


def _fingerprint(row: dict[str, Any]) -> str:
    p = row.get("proposal") or {}
    c = p.get("proposed_change") or {}
    summary = re.sub(r"\s+", " ", str(c.get("summary") or "").strip().lower())
    paths = sorted(str(x).strip().lower() for x in (c.get("allowed_paths") or []))
    return hashlib.sha256((summary + "|" + "|".join(paths)).encode()).hexdigest()[:16]


def tournament(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [dict(r) for r in rows if r.get("eligible")]
    seen: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for row in eligible:
        fp = _fingerprint(row)
        row["proposal_fingerprint"] = fp
        old = seen.get(fp)
        if old is None or float(row.get("score") or 0) > float(old.get("score") or 0):
            if old is not None:
                old["duplicate_of"] = row.get("agent_id")
                duplicates.append(old)
            seen[fp] = row
        else:
            row["duplicate_of"] = old.get("agent_id")
            duplicates.append(row)
    unique = sorted(seen.values(), key=lambda x: (float(x.get("score") or 0), str(x.get("agent_id") or "")), reverse=True)
    champion = unique[0] if unique else None
    return {
        "schema": "agent-factory-tournament/v1",
        "worker_count": len(rows),
        "eligible_count": len(eligible),
        "unique_proposals": len(unique),
        "invalid_count": len(rows) - len(eligible),
        "duplicate_count": len(duplicates),
        "champion": champion,
        "ranked": unique,
        "duplicates": duplicates,
        "rejected": [r for r in rows if not r.get("eligible")],
        "promotion_ready": bool(champion and float(champion.get("score") or 0) >= 60.0),
        "promotion_threshold": 60.0,
    }


def render(result: dict[str, Any]) -> str:
    champ = result.get("champion") or {}
    lines = [
        "# THE WORLD Agent Factory Tournament",
        "",
        f"- workers: {result.get('worker_count')}",
        f"- eligible: {result.get('eligible_count')}",
        f"- unique proposals: {result.get('unique_proposals')}",
        f"- invalid: {result.get('invalid_count')}",
        f"- duplicates: {result.get('duplicate_count')}",
        f"- promotion ready: **{result.get('promotion_ready')}**",
        "",
    ]
    if champ:
        proposal = champ.get("proposal") or {}
        change = proposal.get("proposed_change") or {}
        lines += [
            "## Champion",
            f"- agent: `{champ.get('agent_id')}`",
            f"- role: `{champ.get('role')}` / `{champ.get('stance')}`",
            f"- score: **{champ.get('score')}**",
            f"- hypothesis: {proposal.get('hypothesis')}",
            f"- change: {change.get('summary')}",
            f"- expected delta: {change.get('expected_delta')}",
            f"- paths: {', '.join(change.get('allowed_paths') or [])}",
            "",
        ]
    lines.append("## Ranking")
    for i, row in enumerate(result.get("ranked") or [], 1):
        lines.append(f"{i}. `{row.get('agent_id')}` score={row.get('score')} role={row.get('role')} fp={row.get('proposal_fingerprint')}")
    return "\n".join(lines) + "\n"


def forge_prompt(plan: dict[str, Any], result: dict[str, Any]) -> str:
    champion = result.get("champion") or {}
    if not champion or not result.get("promotion_ready"):
        raise ValueError("no promotion-ready champion")
    proposal = champion.get("proposal") or {}
    change = proposal.get("proposed_change") or {}
    return f"""You are THE WORLD Champion Forge. Implement exactly ONE bounded, reversible improvement selected by the independent Agent Factory tournament.

MISSION
{json.dumps(plan.get('mission') or {}, ensure_ascii=False, indent=2)}

CHAMPION
agent_id: {champion.get('agent_id')}
role: {champion.get('role')}
score: {champion.get('score')}
hypothesis: {proposal.get('hypothesis')}
change: {change.get('summary')}
expected_delta: {change.get('expected_delta')}
evidence_refs: {json.dumps(proposal.get('evidence_refs') or [], ensure_ascii=False)}
counterevidence: {json.dumps(proposal.get('counterevidence') or [], ensure_ascii=False)}
requested_paths: {json.dumps(change.get('allowed_paths') or [], ensure_ascii=False)}
tests: {json.dumps(change.get('tests') or [], ensure_ascii=False)}
rollback: {change.get('rollback')}
limitations: {json.dumps(proposal.get('limitations') or [], ensure_ascii=False)}

HARD CHANGE BOUNDARY
- Modify only files under: automation/ai_foundry/, automation/world/, automation/security/, standment-security/, value-lab/, docs/.
- Do NOT modify .github/, automation/agent_factory/, senju/, outside-world/, tomoki-agents/, ops/, PORTFOLIO.md, secrets, credentials, deployment settings, authorization scope, or external-write systems.
- Do not target third-party systems or add offensive/exploit behavior.
- Do not push, merge, publish, post externally, or create credentials.
- Do not mark anything VERIFIED, commercially validated, model-trained, or capability-improved from strategy proxy alone.
- Keep the change <= 8 files and <= 1500 changed lines total.
- Preserve backward compatibility unless the champion explicitly proves a bounded contract change is necessary.
- Add/update the smallest relevant tests or reproducibility evidence.
- If repository facts contradict the champion hypothesis, make NO CHANGE and write the reason to `agent-factory-forge-report.md`.

IMPLEMENTATION CONTRACT
1. Inspect cited repository evidence before editing.
2. Attempt to falsify the champion once more.
3. Implement only if evidence still supports it.
4. Run the most relevant local tests available to you.
5. Write `agent-factory-forge-report.md` with: what changed, why, files, tests, counterevidence, limitations, rollback, and whether the expected delta was actually observed locally.
6. Stop. A separate policy gate decides whether a PR may be created.
"""


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("normalize")
    q.add_argument("--plan", required=True)
    q.add_argument("--slot", type=int, required=True)
    q.add_argument("--raw", required=True)
    q.add_argument("--out", required=True)
    q = sub.add_parser("tournament")
    q.add_argument("--workers-dir", required=True)
    q.add_argument("--json", required=True)
    q.add_argument("--report", required=True)
    q = sub.add_parser("forge-prompt")
    q.add_argument("--plan", required=True)
    q.add_argument("--result", required=True)
    q.add_argument("--out", required=True)
    args = p.parse_args()

    if args.cmd == "normalize":
        plan = _load(Path(args.plan))
        raw = Path(args.raw).read_text(encoding="utf-8", errors="replace")
        row = normalize(plan, args.slot, raw)
        Path(args.out).write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"agent_id": row.get("agent_id"), "eligible": row.get("eligible"), "score": row.get("score"), "reasons": row.get("reasons")}, ensure_ascii=False))
        return 0

    if args.cmd == "tournament":
        rows = []
        for path in sorted(Path(args.workers_dir).glob("*.json")):
            try:
                rows.append(_load(path))
            except Exception as exc:
                rows.append({"schema": "agent-factory-normalized/v1", "agent_id": path.stem, "eligible": False, "score": 0, "reasons": [f"load_error:{type(exc).__name__}"]})
        result = tournament(rows)
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        Path(args.report).write_text(render(result), encoding="utf-8")
        print(json.dumps({"eligible": result["eligible_count"], "unique": result["unique_proposals"], "promotion_ready": result["promotion_ready"], "champion": (result.get("champion") or {}).get("agent_id"), "score": (result.get("champion") or {}).get("score")}, ensure_ascii=False))
        return 0

    plan = _load(Path(args.plan))
    result = _load(Path(args.result))
    Path(args.out).write_text(forge_prompt(plan, result), encoding="utf-8")
    print((result.get("champion") or {}).get("agent_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
