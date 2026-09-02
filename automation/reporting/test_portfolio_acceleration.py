from datetime import datetime, timezone

from automation.reporting.portfolio_acceleration import (
    build_acceleration_plan,
    choose_batch,
    sprint_day,
)
from automation.reporting.portfolio_evolution import parse_portfolio


SAMPLE = """
# Portfolio

## 1. Verified Tool

**状態: VERIFIED**

### 次の改善
観測性を強化する。

---

## 2. Security Demo

**状態: BUILDING**

### 何に使える？
顧客向けsecurity診断。

### 現在の残り
E2E未確認。

### 次の改善
公開デモを実測する。

---

## 3. Memory Product

**状態: EXPERIMENT**

### 何に使える？
営業データの再利用。

### 次の改善
人間が開けるdashboardを作る。

---

## 4. Blocked Reporter

**状態: BLOCKED**

### 現在の残り
secret未設定。

### 次の改善
外部依存を確認して、別の検証可能部分を進める。

---
"""


def test_sprint_day_is_jst_aware():
    assert sprint_day(datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)) == 1
    assert sprint_day(datetime(2026, 9, 5, 14, 59, tzinfo=timezone.utc)) == 7
    assert sprint_day(datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)) is None


def test_batch_prefers_unfinished_and_caps_at_three():
    batch = choose_batch(parse_portfolio(SAMPLE))
    assert len(batch) == 3
    assert all(item.status != "VERIFIED" for item in batch)


def test_acceleration_plan_has_quality_ladder_and_benchmark():
    plan = build_acceleration_plan(
        parse_portfolio(SAMPLE), datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    )
    assert plan["mode"] == "ACCELERATION_WEEK"
    assert plan["sprint"]["day"] == 1
    assert plan["batch_policy"]["max_parallel_bets"] == 3
    assert plan["batch_policy"]["primary_research_bet"] == 1
    assert plan["promotion_rules"]["human_inspectable_artifact_required"] is True
    assert plan["promotion_rules"]["code_or_pr_alone_is_not_portfolio"] is True
    assert plan["day7_benchmark"]["rerun_day1_class_task"] is True
    assert "architecture" in plan["quality_dimensions"]
    assert "security" in plan["quality_dimensions"]
    assert "human_inspectability" in plan["quality_dimensions"]
