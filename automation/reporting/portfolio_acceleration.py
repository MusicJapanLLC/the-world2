#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation.reporting.portfolio_evolution import PortfolioItem, parse_portfolio

JST = timezone(timedelta(hours=9))
SPRINT_START = datetime(2026, 8, 30, tzinfo=JST).date()
SPRINT_DAYS = 7
MAX_PARALLEL_BETS = 3

DAY_LADDER = {
    1: {
        "theme": "Baseline / Evidence",
        "goal": "現状の実力を測り、再現可能なbaselineと失敗証拠を残す",
        "quality_focus": ["correctness", "reproducibility", "evidence"],
    },
    2: {
        "theme": "Architecture / Test Depth",
        "goal": "責務分離・境界・テスト深度を上げ、壊れにくい設計へ進める",
        "quality_focus": ["architecture", "test_depth", "maintainability"],
    },
    3: {
        "theme": "Reliability / Security",
        "goal": "失敗時の挙動、安全境界、回復性、監査性を実証する",
        "quality_focus": ["reliability", "security", "auditability"],
    },
    4: {
        "theme": "Integration / Automation",
        "goal": "単品コードから、実運用で連携・自動実行できるシステムへ引き上げる",
        "quality_focus": ["integration", "automation", "observability"],
    },
    5: {
        "theme": "Performance / Engineering Quality",
        "goal": "速度・効率・複雑性・変更容易性を測定し、性能劣化なしで改善する",
        "quality_focus": ["performance", "complexity", "maintainability"],
    },
    6: {
        "theme": "Productization / Human UX",
        "goal": "人間が開いて理解・判断・再利用できる成果物へ変換する",
        "quality_focus": ["human_inspectability", "documentation", "delivery"],
    },
    7: {
        "theme": "Capstone / Benchmark",
        "goal": "Day1相当課題を再実装し、7日間で何が改善したか証拠付きで比較する",
        "quality_focus": ["benchmark", "regression", "portfolio_quality"],
    },
}

QUALITY_DIMENSIONS = [
    "correctness",
    "architecture",
    "test_depth",
    "reliability",
    "security",
    "observability",
    "performance",
    "maintainability",
    "reproducibility",
    "human_inspectability",
    "documentation",
    "delivery",
]


def sprint_day(now: datetime) -> int | None:
    today = now.astimezone(JST).date()
    delta = (today - SPRINT_START).days
    if 0 <= delta < SPRINT_DAYS:
        return delta + 1
    return None


def choose_batch(items: list[PortfolioItem], limit: int = MAX_PARALLEL_BETS) -> list[PortfolioItem]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    unfinished = [item for item in items if item.status != "VERIFIED"]
    pool = unfinished if unfinished else items
    return sorted(pool, key=lambda item: (item.score, item.title), reverse=True)[:limit]


def portfolio_metrics(items: list[PortfolioItem]) -> dict:
    total = len(items)
    verified = sum(item.status == "VERIFIED" for item in items)
    unfinished = total - verified
    return {
        "total": total,
        "verified": verified,
        "unfinished": unfinished,
        "verified_ratio": round(verified / total, 4) if total else 0.0,
    }


def build_acceleration_plan(items: list[PortfolioItem], now: datetime) -> dict:
    day = sprint_day(now)
    batch = choose_batch(items)
    profile = DAY_LADDER.get(day) if day else None

    return {
        "schema": "the-world-portfolio-acceleration/v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "mode": "ACCELERATION_WEEK" if profile else "STEADY_STATE",
        "sprint": {
            "start_jst": str(SPRINT_START),
            "days": SPRINT_DAYS,
            "day": day,
            "theme": profile["theme"] if profile else None,
            "goal": profile["goal"] if profile else None,
            "quality_focus": profile["quality_focus"] if profile else [],
        },
        "capability_goal": (
            "Improve the engineering system's measured output quality through evaluation, memory, testing, "
            "verification and reusable patterns; this does not retrain or modify the underlying model weights."
        ),
        "portfolio_metrics": portfolio_metrics(items),
        "batch_policy": {
            "max_parallel_bets": MAX_PARALLEL_BETS,
            "primary_research_bet": 1,
            "rule": (
                "Keep one deep primary research bet for Senju, while advancing up to three independent portfolio "
                "items when they can be verified without diluting evidence quality."
            ),
        },
        "bets": [
            {
                "rank": idx + 1,
                "title": item.title,
                "status": item.status,
                "score": item.score,
                "reasons": list(item.reasons),
                "target": item.next_improvement
                or "人間が開ける成果物と、中核挙動を示す検証証拠を追加する",
            }
            for idx, item in enumerate(batch)
        ],
        "quality_dimensions": QUALITY_DIMENSIONS,
        "promotion_rules": {
            "no_regression_in_core_behavior": True,
            "tests_required_for_claimed_behavior": True,
            "human_inspectable_artifact_required": True,
            "counterevidence_preserved": True,
            "reproducible_evidence_preferred": True,
            "code_or_pr_alone_is_not_portfolio": True,
            "technical_score_is_not_market_evidence": True,
        },
        "daily_learning_contract": {
            "save_failed_hypotheses": True,
            "save_reusable_patterns": True,
            "compare_to_previous_day": True,
            "increase_task_difficulty_when_quality_is_stable": True,
            "do_not_increase_complexity_when_regressing": True,
        },
        "day7_benchmark": {
            "rerun_day1_class_task": True,
            "compare_dimensions": QUALITY_DIMENSIONS,
            "success": (
                "Material improvement must be visible in multiple measured engineering dimensions without a "
                "core-behavior or safety regression."
            ),
        },
    }


def render_slack(plan: dict) -> str:
    sprint = plan["sprint"]
    metrics = plan["portfolio_metrics"]
    lines = [
        "*THE WORLD｜PORTFOLIO ACCELERATION WEEK*",
        f"mode=`{plan['mode']}` / day={sprint['day'] or '-'} / theme={sprint['theme'] or '-'}",
        f"Goal: {sprint['goal'] or '通常のportfolio-first運用'}",
        (
            f"Portfolio: VERIFIED {metrics['verified']}/{metrics['total']} "
            f"/ unfinished={metrics['unfinished']} / ratio={metrics['verified_ratio']:.0%}"
        ),
        "今日のbatch:",
    ]
    for bet in plan["bets"]:
        lines.append(
            f"{bet['rank']}. *{bet['title']}* / {bet['status']} / score={bet['score']} -> {bet['target']}"
        )
    lines.extend(
        [
            "Quality gate: correctness / architecture / tests / reliability / security / observability / performance / maintainability / reproducibility / human UX / docs / delivery.",
            "学習: 成功だけでなく失敗仮説・反証・再利用パターンを保存し、翌日は昨日より難しい課題へ進む。",
            "Day7: Day1相当課題を再実装し、同じ物差しで差分を測る。モデル重みの自己改変ではなく、開発システムの実測能力を上げる。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="PORTFOLIO.md")
    ap.add_argument("--out", default="reports/portfolio-evolution/acceleration.json")
    ap.add_argument("--slack", default="reports/portfolio-evolution/acceleration.md")
    args = ap.parse_args()

    text = Path(args.portfolio).read_text(encoding="utf-8")
    plan = build_acceleration_plan(parse_portfolio(text), datetime.now(timezone.utc))

    out = Path(args.out)
    slack = Path(args.slack)
    out.parent.mkdir(parents=True, exist_ok=True)
    slack.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slack.write_text(render_slack(plan) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "mode": plan["mode"],
                "day": plan["sprint"]["day"],
                "bets": [bet["title"] for bet in plan["bets"]],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
