#!/usr/bin/env python3
"""Continuous defensive portfolio research for the Standment Elite White-Hat Cell.

This worker is evidence-first, target-free and defensive. It never attacks networks.
A machine-readable Research Frontier defines the lenses. Each micro-round rotates both
lens and research stage so repeated workflow runs deepen the work instead of rereading
the same topics. A public-framework crosswalk provides an external benchmark layer;
alignment never counts as verification by itself.

A bounded AI-security evaluation hint may nominate a preferred lens. That hint is used
for only two of ten rounds (1 and 6), leaving the rest of the cycle broad and rotating.
The hint cannot alter scope, permissions, promotion gates or VERIFIED status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRONTIER_PATH = Path("standment-security/security_research_frontier.json")
PROGRAM_PATH = Path("standment-security/security_portfolio_program.json")
CROSSWALK_PATH = Path("standment-security/security_framework_crosswalk.json")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _numeric_run_seed(run_id: str) -> int:
    match = re.search(r"\d+", str(run_id))
    if match:
        return int(match.group(0))
    return int(hashlib.sha256(str(run_id).encode()).hexdigest()[:12], 16)


def _select(
    frontier: dict[str, Any],
    run_id: str,
    round_number: int,
    preferred_lens: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    lenses = [x for x in frontier.get("lenses", []) if isinstance(x, dict)]
    stages = [str(x) for x in (frontier.get("selection_policy", {}).get("stages") or []) if str(x)]
    stage_contracts = frontier.get("stage_contracts") if isinstance(frontier.get("stage_contracts"), dict) else {}
    if not lenses:
        raise ValueError("security research frontier has no lenses")
    if not stages:
        raise ValueError("security research frontier has no stages")

    global_micro = (_numeric_run_seed(run_id) * 5) + max(0, round_number - 1)
    by_id = {str(x.get("id") or ""): x for x in lenses}
    preferred = by_id.get(str(preferred_lens or ""))
    if preferred is not None and round_number in {1, 6}:
        lens = preferred
    else:
        lens = lenses[global_micro % len(lenses)]
    stage = stages[(global_micro // len(lenses)) % len(stages)]
    contract = str(stage_contracts.get(stage) or "Evidence-first bounded defensive research")
    return lens, stage, contract


def _framework_alignment(crosswalk: dict[str, Any], lens_id: str) -> list[dict[str, str]]:
    mappings = crosswalk.get("lens_mapping") if isinstance(crosswalk.get("lens_mapping"), dict) else {}
    catalog = crosswalk.get("frameworks") if isinstance(crosswalk.get("frameworks"), dict) else {}
    keys = [str(x) for x in (mappings.get(lens_id) or []) if str(x)]
    rows: list[dict[str, str]] = []
    for key in keys[:5]:
        meta = catalog.get(key) if isinstance(catalog.get(key), dict) else {}
        rows.append({
            "id": key,
            "name": str(meta.get("name") or key),
            "use": str(meta.get("use") or "external defensive benchmark"),
            "url": str(meta.get("url") or ""),
        })
    return rows


def _file_signals(root: Path, present: list[str]) -> dict[str, Any]:
    keywords = {
        "authorization": ("authorization", "authorized", "scope", "owner"),
        "behavior": ("observed", "before", "after", "retest", "pass", "fail"),
        "counterevidence": ("counterevidence", "falsif", "alternative", "limitation"),
        "reproducibility": ("reproduc", "rerun", "repeat", "deterministic"),
        "customer_readability": ("customer", "buyer", "executive", "use case", "用途"),
    }
    hits = {k: 0 for k in keywords}
    inspected = 0
    for rel in present[:8]:
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()[:120000]
        except Exception:
            continue
        inspected += 1
        for category, words in keywords.items():
            if any(word.lower() in text for word in words):
                hits[category] += 1
    return {"inspected_files": inspected, "signal_hits": hits}


def _stage_question(stage: str, lens: dict[str, Any], missing: list[str], frameworks: list[dict[str, str]]) -> str:
    title = str(lens.get("title") or lens.get("id") or "security control")
    benchmark = ", ".join(x["id"] for x in frameworks[:3]) or "internal baseline only"
    if stage == "DISCOVERY":
        return f"{title}で、今ある証拠と『まだ証明できていないこと』の境界はどこか？ 外部照合: {benchmark}"
    if stage == "FALSIFICATION":
        return f"{title}の安全性主張を間違いだと示せる反証条件は何か？ 外部照合: {benchmark}"
    if stage == "REMEDIATION":
        return f"{title}の最大の証拠ギャップを、最小・可逆な改善でどう縮めるか？ 外部照合: {benchmark}"
    if stage == "RETEST":
        return f"{title}を同一条件で再実行し、Before/After差分をどう独立確認するか？ 外部照合: {benchmark}"
    gap = missing[0] if missing else "runtime / independent retest evidence"
    return f"{title}を顧客がコードを読まず判断できるEvidence Cardへ変換する時、最後に不足する証拠は何か？ ({gap}) 外部照合: {benchmark}"


def _next_improvement(stage: str, lens: dict[str, Any], missing: list[str]) -> str:
    safe_test = str(lens.get("safe_test") or "所有/明示許可済みfixtureで非破壊検証する")
    if stage == "DISCOVERY":
        return f"不足Evidenceを1つだけ選び、検証可能な仮説へ変換する。最優先候補: {missing[0] if missing else 'runtime behavioral evidence'}"
    if stage == "FALSIFICATION":
        return f"既存主張を否定できる条件を1つ固定し、{safe_test}で反証可能性を定義する"
    if stage == "REMEDIATION":
        return "最大の証拠ギャップに対して、変更範囲・期待差分・rollbackを持つ最小改善案を作る"
    if stage == "RETEST":
        return f"{safe_test}。同一入力・同一判定基準でBefore/Afterを比較し、失敗条件も保存する"
    return "技術証拠を『用途 / Before / After / 検証 / 外部基準 / 反証 / 残存リスク / 再現方法』の1枚に束ねる"


def run_round(root: Path, round_number: int, run_id: str, preferred_lens: str | None = None) -> dict[str, Any]:
    frontier = _load_json(root / FRONTIER_PATH)
    lens, stage, stage_contract = _select(frontier, run_id, round_number, preferred_lens)
    crosswalk = _load_json(root / CROSSWALK_PATH)
    frameworks = _framework_alignment(crosswalk, str(lens.get("id") or ""))

    refs = [str(x) for x in (lens.get("refs") or []) if isinstance(x, str)]
    present = [p for p in refs if (root / p).exists()]
    missing = [p for p in refs if not (root / p).exists()]
    ratio = round(len(present) / max(1, len(refs)), 3)
    signals = _file_signals(root, present)

    program = _load_json(root / PROGRAM_PATH)
    tracks = [x for x in program.get("tracks", []) if isinstance(x, dict)]
    related = []
    words = set(str(lens.get("title") or "").lower().replace("/", " ").split())
    for track in tracks:
        blob = " ".join(str(track.get(k, "")) for k in ("id", "title", "hypothesis", "deliverable", "customer_usefulness")).lower()
        overlap = sum(1 for w in words if len(w) >= 4 and w in blob)
        if overlap:
            related.append((overlap, str(track.get("id") or ""), str(track.get("title") or "")))
    related.sort(reverse=True)

    challenge = (
        "リポジトリ上のファイル、キーワード、外部フレームワークへの対応表は、ランタイム挙動・顧客価値・脆弱性不在を証明しない。"
        "VERIFIEDには所有/明示許可済みscope、行動証拠、反証、再実行性、独立retestが必要。"
    )
    next_improvement = _next_improvement(stage, lens, missing)
    question = _stage_question(stage, lens, missing, frameworks)
    assisted = bool(preferred_lens) and str(lens.get("id") or "") == str(preferred_lens) and round_number in {1, 6}
    fingerprint_src = json.dumps(
        {
            "lens": lens.get("id"),
            "stage": stage,
            "present": present,
            "missing": missing,
            "frameworks": [x["id"] for x in frameworks],
            "next": next_improvement,
            "selection_source": "ai_security_eval" if assisted else "broad_rotation",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(fingerprint_src.encode()).hexdigest()[:16]

    blockers = []
    if missing:
        blockers.append("configured_evidence_missing")
    if not frameworks:
        blockers.append("external_framework_alignment_missing")
    if signals["signal_hits"].get("behavior", 0) == 0:
        blockers.append("no_behavioral_evidence_signal")
    if signals["signal_hits"].get("counterevidence", 0) == 0:
        blockers.append("no_counterevidence_signal")
    if signals["signal_hits"].get("reproducibility", 0) == 0:
        blockers.append("no_reproducibility_signal")
    blockers.append("runtime_and_customer_validation_not_inferred_from_repository")

    return {
        "schema": "elite-whitehat-continuous-round/v4",
        "run_id": run_id,
        "round": round_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lens_id": lens.get("id"),
        "research_stage": stage,
        "stage_contract": stage_contract,
        "selection_source": "ai_security_eval" if assisted else "broad_rotation",
        "preferred_lens": preferred_lens,
        "research_question": question,
        "artifact": lens.get("title"),
        "use_case": lens.get("purpose"),
        "customer_use": lens.get("customer_use"),
        "safe_test_contract": lens.get("safe_test"),
        "external_frameworks": frameworks,
        "evidence": {"present": present, "missing": missing, "coverage": ratio, "signals": signals},
        "related_portfolio": [{"id": x[1], "title": x[2]} for x in related[:3]],
        "counterevidence": challenge,
        "promotion_blockers": blockers,
        "status": "BUILDING",
        "next_improvement": next_improvement,
        "fingerprint": fingerprint,
    }


def render_card(row: dict[str, Any]) -> str:
    ev = row["evidence"]
    related = ", ".join(x["id"] for x in row.get("related_portfolio", [])) or "NONE"
    frameworks = ", ".join(x["id"] for x in row.get("external_frameworks", [])) or "NONE"
    missing = ", ".join(ev["missing"]) if ev["missing"] else "NONE"
    blockers = ", ".join(row.get("promotion_blockers") or []) or "NONE"
    return "\n".join([
        f"# SECURITY PORTFOLIO MICRO ROUND {row['round']}",
        "",
        f"- 研究Stage: **{row['research_stage']}**",
        f"- 成果物: **{row['artifact']}**",
        f"- 選定元: **{row.get('selection_source', 'broad_rotation')}**",
        f"- Eval優先Lens: **{row.get('preferred_lens') or 'NONE'}**",
        f"- 研究質問: {row['research_question']}",
        f"- 用途: {row['use_case']}",
        f"- 顧客が使う場面: {row['customer_use']}",
        f"- 外部基準: {frameworks}",
        f"- 安全な検証契約: {row['safe_test_contract']}",
        f"- Evidence coverage: **{ev['coverage']:.0%}** ({len(ev['present'])}/{len(ev['present']) + len(ev['missing'])})",
        f"- 不足Evidence: {missing}",
        f"- 関連Portfolio: {related}",
        f"- 反証/限界: {row['counterevidence']}",
        f"- Promotion blocker: {blockers}",
        f"- 現在ステータス: **{row['status']}**",
        f"- 次の改善: {row['next_improvement']}",
        f"- fingerprint: `{row['fingerprint']}`",
        "",
    ])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--preferred-lens")
    args = p.parse_args()

    root = Path.cwd()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    row = run_round(root, args.round, args.run_id, args.preferred_lens)
    stem = f"round-{args.round:02d}"
    (out / f"{stem}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / f"{stem}.md").write_text(render_card(row), encoding="utf-8")
    print(json.dumps({
        "round": args.round,
        "lens": row["lens_id"],
        "stage": row["research_stage"],
        "selection_source": row["selection_source"],
        "artifact": row["artifact"],
        "frameworks": [x["id"] for x in row["external_frameworks"]],
        "coverage": row["evidence"]["coverage"],
        "fingerprint": row["fingerprint"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
