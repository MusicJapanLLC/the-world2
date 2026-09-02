# Standment Security Evidence Dashboard

Status: **BUILDING**

## Purpose

Standment Securityのポートフォリオについて、**何が実在し、何が未検証で、次に何を埋めれば顧客へ見せられるか**を1枚で追えるようにする。

ダッシュボードの目的は報告量を増やすことではない。研究・白帽子レビュー・Senju・Auto-Builderの出力を、**Portfolio readiness**へ変換すること。

## Portfolio States

- `ABSENT` — まだ人間が確認できる成果物がない
- `BUILDING` — 成果物はあるがEvidence不足
- `PROMOTION_READY` — 必須Evidenceが揃い、最終確認待ち
- `VERIFIED` — 再現・retest・counterevidence・limitationsを含む確認済み成果物
- `BLOCKED` — 外部依存、権限、再現性などの具体的ブロッカーあり

## North Star

毎日追う指標は以下だけに絞る。

1. `tracks_verified`
2. `tracks_full_evidence`
3. `average_evidence_ratio`
4. `whitehat_candidates_open`
5. `independent_retests_completed`
6. `stagnating_tracks`
7. `days_since_material_portfolio_delta`

「研究回数」「生成文字数」「エージェント数」はNorth Starにしない。

## Current Security Portfolio Map

| Track | Asset | Primary proof needed |
|---|---|---|
| SEC-PORT-001 | Security Scan Before/After | same-condition retest + customer-readable delta |
| SEC-PORT-002 | Customer Security Evidence Pack | complete example evidence bundle |
| SEC-PORT-003 | Supply-chain Evidence Portfolio | reproducible gate outputs + limitations |
| SEC-PORT-004 | Auth / Tenant / RLS Evidence Kit | owned fixture before/after authorization evidence |
| SEC-PORT-005 | Agent Security & Auditability Pack | allowed/denied/action-log proof |
| SEC-PORT-006 | Incident Readiness Pack | recovery/rollback evidence |
| SEC-PORT-007 | Continuous Security Scorecard | recurring evidence freshness + regression delta |
| SEC-PORT-008 | Security Architecture Review Pack | inspectable sample review + evidence links |
| SEC-PORT-009 | AI Agent Permission Boundary Lab | boundary matrix + independent retest |
| SEC-PORT-010 | LLM Security Evaluation Harness | reproducible eval cases + regression evidence |
| SEC-PORT-011 | Security Evidence Dashboard | machine-readable daily truth state |

## Daily Decision Rule

毎日のR&Dは次の順で1つのmaterial deltaを狙う。

1. **Close** — VERIFIEDに最も近いTrackの欠けたEvidenceを1つ埋める
2. **Challenge** — white-hatが最重要仮説を反証する
3. **Improve** — Senjuが再現性・学習効率・反証品質を改善する
4. **Retest** — 別run/clean fixtureで同じ判定基準を再実行する
5. **Package** — 人間が読めるBefore/After・Evidence Packへ変換する
6. **Report** — Slackには「何が変わった / なぜ重要 / 何がまだ未証明 / 次は何か」だけを送る

## Anti-Stagnation Rule

同一Trackでmaterial portfolio deltaが出ない場合:

- 1日目: 次の最小Evidenceへ集中
- 2日目: Senjuが仮説を再構成しcounterevidenceを優先
- 3日目: 同じ実験の反復を禁止し、別Evidence pathまたは別Trackへ切り替える

停滞を「継続研究」と言い換えない。

## White-Hat Integration

white-hat candidateは脆弱性数では評価しない。

価値があるcandidateは次を持つ。

- bounded/authorized hypothesis
- reproducible safe experiment
- falsifier/counterevidence
- smallest defensive remediation
- independent retest criterion
- residual risk
- customer-readable impact

CandidateだけではVERIFIEDにならない。

## Senju Integration

Senjuは次を最適化する。

- hypothesis quality
- reproducibility
- counterevidence quality
- experiment efficiency
- selection robustness

Senjuのscore単体をPortfolio Evidenceにしない。

## Slack Reporting Contract

毎日R&Dチャンネルへ以下を送る。

1. **WHAT CHANGED** — 前回からの実差分
2. **WHY IT MATTERS** — 技術/顧客価値
3. **PORTFOLIO DELTA** — Evidence ratio / status / artifact
4. **WHITE-HAT** — 反証・finding・retest status
5. **SENJU** — 研究方法の改善点
6. **TRUTH** — 未検証・limitations・blocker
7. **NEXT MOVE** — 次の最小Evidence

`#portfolio`には、顧客が開いて見られる成果物またはPromotion Ready/Verifiedのmaterial deltaだけを流す。

## Promotion Rule

自動化はEvidenceを集め、`PROMOTION_READY`までは判定してよい。

`VERIFIED`を名乗るには、少なくとも以下がinspectableであること。

- authorization basis
- reproducible test
- before/after evidence where applicable
- independent retest
- counterevidence/falsifier
- limitations/residual risk
- rollback/recovery note
- human-readable artifact

## Company Priority

Standment Security Portfolio R&D = **THE WORLD P0**

通常の研究量より、**顧客が確認できる防御Evidenceを増やすこと**を優先する。