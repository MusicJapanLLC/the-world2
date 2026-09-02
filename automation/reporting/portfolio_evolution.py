#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SECTION_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)
STATUS_RE = re.compile(r"\*\*状態:\s*([A-Z]+)\*\*")
NEXT_RE = re.compile(r"###\s+次の改善\s*\n(.+?)(?=\n###|\n---|\Z)", re.DOTALL)

STATUS_BASE = {
    "BLOCKED": 105,
    "BUILDING": 82,
    "EXPERIMENT": 68,
    "VERIFIED": 18,
}

PROOF_GAP_TERMS = (
    "未確認", "未完了", "残り", "証拠", "実測", "e2e", "scheduled run",
    "初回", "secret", "blocked", "dogfood", "公開", "検証",
)
CUSTOMER_VALUE_TERMS = (
    "顧客", "営業", "商品", "納品", "売上", "saas", "レポート", "診断",
    "dashboard", "デモ", "web app", "website", "artifact", "成果物",
)
SECURITY_PRIORITY_TERMS = (
    "standment security", "security scan", "security company", "security portfolio",
    "セキュリティ", "security",
)


@dataclass(frozen=True)
class PortfolioItem:
    title: str
    status: str
    body: str
    next_improvement: str
    score: int
    reasons: tuple[str, ...]


def _blocks(text: str) -> Iterable[tuple[str, str]]:
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield match.group(1).strip(), text[start:end].strip()


def score_item(title: str, status: str, body: str, next_improvement: str) -> tuple[int, tuple[str, ...]]:
    haystack = f"{title}\n{body}\n{next_improvement}".lower()
    score = STATUS_BASE.get(status, 55)
    reasons: list[str] = [f"status={status}"]

    gap_hits = sum(1 for term in PROOF_GAP_TERMS if term.lower() in haystack)
    if gap_hits:
        bonus = min(30, gap_hits * 5)
        score += bonus
        reasons.append(f"proof_gap+{bonus}")

    value_hits = sum(1 for term in CUSTOMER_VALUE_TERMS if term.lower() in haystack)
    if value_hits:
        bonus = min(18, value_hits * 3)
        score += bonus
        reasons.append(f"customer_value+{bonus}")

    if any(term in haystack for term in SECURITY_PRIORITY_TERMS):
        score += 60
        reasons.append("standment_security_priority+60")

    if next_improvement:
        score += 10
        reasons.append("next_action+10")

    if status == "VERIFIED":
        score -= 12
        reasons.append("already_verified-12")

    return score, tuple(reasons)


def parse_portfolio(text: str) -> list[PortfolioItem]:
    items: list[PortfolioItem] = []
    for title, body in _blocks(text):
        status_match = STATUS_RE.search(body)
        status = status_match.group(1).upper() if status_match else "UNKNOWN"
        next_match = NEXT_RE.search(body)
        next_improvement = " ".join(next_match.group(1).strip().split()) if next_match else ""
        score, reasons = score_item(title, status, body, next_improvement)
        items.append(PortfolioItem(title, status, body, next_improvement, score, reasons))
    return items


def parse_live_evidence(payload: dict) -> list[PortfolioItem]:
    """Turn real production probes into portfolio candidates.

    Healthy sites stay low priority. Reachability, HTTP, health-route, or latency regressions
    become BUILDING/BLOCKED candidates so the next evolution cycle reacts to reality rather
    than only to the prose in PORTFOLIO.md.
    """
    items: list[PortfolioItem] = []
    for row in payload.get("targets") or []:
        name = str(row.get("name") or row.get("id") or "Unnamed target")
        reachable = bool(row.get("reachable"))
        status_code = int(row.get("status_code") or 0)
        expected = {int(x) for x in (row.get("expected_status") or [200])}
        latency_ms = int(row.get("latency_ms") or 0)
        budget_ms = int(row.get("latency_budget_ms") or 3000)
        health_ok = row.get("health_ok")

        reasons = ["live_production_probe"]
        if not reachable:
            status = "BLOCKED"
            score = 210
            reasons += ["unreachable+105", "production_regression+80"]
            next_step = "Restore production reachability, verify HTTP recovery, then run the same probe again before any feature work."
        elif status_code not in expected:
            status = "BLOCKED"
            score = 195
            reasons += [f"unexpected_http={status_code}", "production_regression+75"]
            next_step = f"Restore an expected production HTTP status (observed {status_code}), then preserve a before/after probe as evidence."
        elif health_ok is False:
            status = "BUILDING"
            score = 175
            reasons += ["health_route_failed+70", "production_regression+55"]
            next_step = "Repair the production health path or underlying runtime, then confirm both homepage and health route succeed in the same cycle."
        elif latency_ms > budget_ms:
            status = "BUILDING"
            over = latency_ms - budget_ms
            score = 125 + min(35, max(1, over // 250))
            reasons += [f"latency={latency_ms}ms", f"budget={budget_ms}ms", "performance_regression"]
            next_step = f"Reduce production latency below {budget_ms}ms and keep a measured before/after result; current observation is {latency_ms}ms."
        else:
            status = "VERIFIED"
            score = 20
            reasons += [f"http={status_code}", f"latency={latency_ms}ms", "production_healthy"]
            next_step = "Keep the live target healthy while selecting the next customer-visible, measurable improvement from evidence."

        priority = str(row.get("priority") or "P2")
        if priority == "P0" and status != "VERIFIED":
            score += 35
            reasons.append("target_priority=P0+35")
        elif priority == "P1" and status != "VERIFIED":
            score += 15
            reasons.append("target_priority=P1+15")

        body = (
            f"Live target: {row.get('url','')}\n"
            f"HTTP={status_code} reachable={reachable} latency_ms={latency_ms} "
            f"budget_ms={budget_ms} health_ok={health_ok}"
        )
        items.append(PortfolioItem(
            title=f"Live Site — {name}",
            status=status,
            body=body,
            next_improvement=next_step,
            score=score,
            reasons=tuple(reasons),
        ))
    return items


def choose_primary(items: list[PortfolioItem]) -> PortfolioItem:
    if not items:
        raise ValueError("PORTFOLIO.md contains no numbered portfolio sections")
    return sorted(items, key=lambda item: (item.score, item.title), reverse=True)[0]


def choose_senju_focus(item: PortfolioItem) -> str:
    text = f"{item.title} {item.body} {item.next_improvement}".lower()
    if any(term in text for term in ("安全", "security", "安定", "検証", "証拠", "replay", "risk", "health", "http")):
        return "robustness"
    if any(term in text for term in ("速度", "効率", "工数", "自動", "定期", "運用", "delivery", "report", "latency")):
        return "efficiency"
    if any(term in text for term in ("balance", "偏り", "公平", "coverage", "カバレッジ")):
        return "balance"
    return "learning"


def build_plan(items: list[PortfolioItem], now: datetime) -> dict:
    primary = choose_primary(items)
    focus = choose_senju_focus(primary)
    next_step = primary.next_improvement or "人間が開ける成果物と、その中核挙動の検証証拠を1つ増やす"
    research_id = "RND-PORTFOLIO-P0-001"
    return {
        "schema": "the-world-portfolio-evolution/v2",
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "priority": "P0",
        "organization_priority": "STANDMENT_SECURITY_PORTFOLIO_FIRST",
        "doctrine": (
            "One material portfolio improvement per cycle; live production regressions outrank cosmetic work; evidence before claims. "
            "While Standment Security has unfinished customer-inspectable work, security portfolio receives an explicit P0 scoring advantage across THE WORLD."
        ),
        "portfolio_count": len(items),
        "primary": {
            "title": primary.title,
            "status": primary.status,
            "score": primary.score,
            "reasons": list(primary.reasons),
            "today_target": next_step,
        },
        "senju_directive": {
            "schema": "rnd-senju-directive/v1",
            "research_id": research_id,
            "focus": focus,
            "candidate_count": 7,
            "hypothesis": (
                f"Portfolio P0: '{primary.title}' の proof-to-artifact conversion を最優先にし、"
                f"Senju の {focus} 観点で技術証拠生成の再現性を高めれば、"
                "人間が確認できる VERIFIED 成果物への昇格速度を上げられる。"
            )[:600],
        },
        "gates": {
            "human_inspectable_artifact_required": True,
            "verified_requires_access_and_behavioral_evidence": True,
            "code_or_pr_alone_is_not_portfolio": True,
            "senju_technical_score_is_not_market_evidence": True,
            "standment_security_priority_is_research_priority_not_fake_proof": True,
            "live_regression_preempts_cosmetic_work": True,
        },
        "daily_loop": [
            "PROBE registered production targets",
            "OBSERVE PORTFOLIO.md and live evidence",
            "RANK production/proof/value gaps with Standment Security P0 bias",
            "CHOOSE exactly one primary bet",
            "FORM hypothesis and counterevidence target",
            "SEND bounded directive to Senju",
            "BUILD/VERIFY through existing workers",
            "PORTFOLIO GATE human-inspectable output",
            "REPORT material delta to Slack",
            "SAVE next hypothesis",
        ],
    }


def render_slack(plan: dict) -> str:
    p = plan["primary"]
    d = plan["senju_directive"]
    return (
        "*THE WORLD｜R&D PORTFOLIO P0 — EVOLUTION CYCLE*\n"
        f"組織優先: `{plan['organization_priority']}`\n"
        f"今回の最優先: *{p['title']}* / status=`{p['status']}` / score={p['score']}\n"
        f"選定理由: {', '.join(p.get('reasons') or [])}\n"
        f"今回の改善: {p['today_target']}\n"
        f"千寿連携: `{d['research_id']}` / focus=`{d['focus']}` / candidates={d['candidate_count']}\n"
        f"仮説: {d['hypothesis']}\n"
        "Gate: 本番退行は見た目改善より優先。人間が開ける実物 + 中核挙動の証拠が揃うまで VERIFIED にしない。コード/PRだけはポートフォリオ扱いしない。\n"
        "運用: 1 cycle = 1 material improvement。反証・失敗も保存し、次cycleの仮説へ戻す。\n"
        "※Security優先は研究配分であり、未検証の成果を良く見せるための加点ではない。千寿の技術スコアも市場需要・契約・入金の証拠ではない。"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="PORTFOLIO.md")
    ap.add_argument("--live-evidence", default="")
    ap.add_argument("--out", default="reports/portfolio-evolution/plan.json")
    ap.add_argument("--slack", default="reports/portfolio-evolution/slack.md")
    ap.add_argument("--directive", default="reports/portfolio-evolution/directive.json")
    args = ap.parse_args()

    text = Path(args.portfolio).read_text(encoding="utf-8")
    items = parse_portfolio(text)
    live_count = 0
    if args.live_evidence and Path(args.live_evidence).exists():
        payload = json.loads(Path(args.live_evidence).read_text(encoding="utf-8"))
        live_items = parse_live_evidence(payload)
        items.extend(live_items)
        live_count = len(live_items)

    plan = build_plan(items, datetime.now(timezone.utc))
    plan["live_target_count"] = live_count

    out = Path(args.out)
    slack = Path(args.slack)
    directive = Path(args.directive)
    out.parent.mkdir(parents=True, exist_ok=True)
    slack.parent.mkdir(parents=True, exist_ok=True)
    directive.parent.mkdir(parents=True, exist_ok=True)

    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slack.write_text(render_slack(plan) + "\n", encoding="utf-8")
    directive.write_text(json.dumps(plan["senju_directive"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "priority": plan["priority"],
        "organization_priority": plan["organization_priority"],
        "primary": plan["primary"]["title"],
        "status": plan["primary"]["status"],
        "senju_focus": plan["senju_directive"]["focus"],
        "live_target_count": live_count,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
