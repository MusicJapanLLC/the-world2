from datetime import datetime, timezone

from automation.reporting.portfolio_evolution import (
    build_plan,
    choose_primary,
    parse_live_evidence,
    parse_portfolio,
)


SAMPLE = """
# Portfolio

## 1. Stable Product

**状態: VERIFIED**

### 何に使える？
顧客向けレポート。

### 次の改善
軽微な文言改善。

---

## 2. Customer Demo

**状態: BUILDING**

### 何に使える？
顧客が開けるWeb appと診断レポート。

### 現在の残り
E2E未確認。公開環境の検証証拠が必要。

### 次の改善
公開デモを実測し、Before/After証拠をケーススタディ化する。

---
"""


SECURITY_SAMPLE = """
# Portfolio

## 1. Generic Customer Demo

**状態: BUILDING**

### 何に使える？
顧客向けWeb app。

### 次の改善
公開環境を検証する。

---

## 2. Standment Security Evidence Pack

**状態: BUILDING**

### 何に使える？
セキュリティ診断の証拠を顧客へ納品する。

### 次の改善
Before/After証拠と再現性を検証する。

---
"""


def test_parse_and_choose_unverified_high_value_gap():
    items = parse_portfolio(SAMPLE)
    assert len(items) == 2
    primary = choose_primary(items)
    assert primary.title == "Customer Demo"
    assert primary.status == "BUILDING"
    assert primary.next_improvement.startswith("公開デモ")


def test_build_plan_is_p0_and_bounded_for_senju():
    plan = build_plan(parse_portfolio(SAMPLE), datetime(2026, 8, 30, tzinfo=timezone.utc))
    directive = plan["senju_directive"]
    assert plan["priority"] == "P0"
    assert plan["organization_priority"] == "STANDMENT_SECURITY_PORTFOLIO_FIRST"
    assert directive["research_id"] == "RND-PORTFOLIO-P0-001"
    assert directive["focus"] in {"robustness", "learning", "balance", "efficiency"}
    assert 3 <= directive["candidate_count"] <= 9
    assert plan["gates"]["human_inspectable_artifact_required"] is True
    assert plan["gates"]["senju_technical_score_is_not_market_evidence"] is True
    assert plan["gates"]["standment_security_priority_is_research_priority_not_fake_proof"] is True
    assert plan["gates"]["live_regression_preempts_cosmetic_work"] is True


def test_verified_item_loses_to_material_building_gap():
    items = parse_portfolio(SAMPLE)
    scores = {item.title: item.score for item in items}
    assert scores["Customer Demo"] > scores["Stable Product"]


def test_standment_security_gets_explicit_world_wide_p0_bias():
    items = parse_portfolio(SECURITY_SAMPLE)
    primary = choose_primary(items)
    assert primary.title == "Standment Security Evidence Pack"
    assert "standment_security_priority+60" in primary.reasons


def test_live_production_regression_preempts_normal_portfolio_work():
    live = parse_live_evidence({
        "targets": [
            {
                "id": "madlab",
                "name": "MADLAB DeepGuard",
                "url": "https://example.invalid/",
                "reachable": False,
                "status_code": 0,
                "expected_status": [200],
                "latency_ms": 0,
                "latency_budget_ms": 3000,
                "priority": "P0",
            }
        ]
    })
    primary = choose_primary(parse_portfolio(SAMPLE) + live)
    assert primary.title == "Live Site — MADLAB DeepGuard"
    assert primary.status == "BLOCKED"
    assert "production_regression+80" in primary.reasons


def test_healthy_live_target_stays_low_priority():
    live = parse_live_evidence({
        "targets": [
            {
                "id": "healthy",
                "name": "Healthy Site",
                "url": "https://example.com/",
                "reachable": True,
                "status_code": 200,
                "expected_status": [200],
                "latency_ms": 250,
                "latency_budget_ms": 3000,
                "priority": "P1",
            }
        ]
    })
    primary = choose_primary(parse_portfolio(SAMPLE) + live)
    assert primary.title == "Customer Demo"
