# AI Factory Portfolio

最終実測: **2026-08-30 JST**

Music Japan / Standment のAI開発工場が**実際に作り、現在どこまで動作確認できているか**を、人間向けにまとめた正本です。

## 今日のPortfolio Blitz

- **VERIFIED: 8 / 9**
- **BLOCKED: 1 / 9**
- **BUILDING: 0 / 9**
- **EXPERIMENT: 0 / 9**

`VERIFIED` はコードやPRがあるだけでは付けません。**人間が確認できる成果物 + 主張した中核挙動の実測証拠**が必要です。

ステータス:
- **VERIFIED** = 実装 + 中核挙動の検証証拠あり
- **BUILDING** = 実物あり、最終統合/検証が残る
- **EXPERIMENT** = ラボ/試作段階
- **BLOCKED** = 実物はあるが外部依存で停止

---

## 1. Senju — GitHub-native Self-Improving Engineering Lab

**状態: VERIFIED**

### 何を作った？
前日のChampionを引き継ぎ、候補戦略を生成・競争・評価し、安全条件とholdoutを通った状態だけを昇格させるGitHub-native自己改善基盤。

### 何に使える？
AI Engineer / Security / QA / R&Dの改善案を、人間が毎回手で比較せず、継続的に競争・反証・検証できる。

### 実測証拠
- default branch上でvalidated stateを自律昇格した run `33253144926`
- promoted commit `97528375730751784f213eab6291c4cfa70780f7`
- PR #67 merged
- `senju/state/last-evolution-summary.json`: safe / source evidence / multi-seed holdout stable+safe
- `senju/state/last-evolution-plan.md`: 人間向け結果あり

### 限界
Senjuの内部スコアは市場需要・契約・入金の証拠ではない。

### 次の改善
自律昇格成功率、no-op率、holdout失敗率を継続計測し、Portfolioへ実物差分だけ還流する。

---

## 2. Standment Security Company Baseline v0.3

**状態: VERIFIED**

### 何を作った？
Standment自身と将来の顧客納品で使う、認証・Secrets・データ・CI/CD・バックアップ・監視・Evidenceの会社共通セキュリティ基準。

### 何に使える？
セキュリティを個人知識ではなく、診断・継続保守・納品品質の共通基準として再利用できる。

### 実測証拠
- PR #29 merged
- owned / authorized scope境界
- MFA/passkey / secret管理
- tenant / external ingest
- backup / RPO / RTO / observability
- customer evidence / KEEP・REVERT・BLOCKED基準

### 次の改善
Security Scanの実診断結果をBaselineへマッピングし、顧客向けControl Evidence Packを増やす。

---

## 3. Standment Security Scan v1

**状態: VERIFIED**

### 何を作った？
明示的に許可されたWebサイトだけを対象に、HTTPS/TLS・Security Headers・Cookie・HTML設定・限定的な公開ファイル露出を**読み取り専用**で確認する診断エンジン。

### 何に使える？
Webサイト/SaaSの初期診断、改善レポート、修正後の再診断、月額Security Watchの納品物に使える。

### 実測証拠
- staleだったPR #31を破棄し、最新THE WORLD上でPR #114として再構築・merge
- merged commit `7a9909c75efe0137bdd75c2b12d2dcd4086a8461`
- current-base run `33265553333`: SUCCESS
- Scanner unit tests: SUCCESS
- 許可済みBaton productionを実診断: **100 / 100, Grade A, passed=True**
- 日本語Markdown + JSON + indexの3ファイルを生成
- evidence artifact `9718531385`, 90日保持
- Security Guard / CodeQL / Dependency Review / Vulnerability Audit / Standment Security Gate 全PASS

### 安全境界
認証突破、ブルートフォース、exploit、fuzzing、負荷試験、データ変更はしない。allowlist-only / read-only。

### 次の改善
実際に設定不備がある所有資産でBefore / Afterケーススタディを作り、営業で見せられるEvidence Packへ育てる。

---

## 4. Revenue Recovery AI — External Ingest Hardening

**状態: VERIFIED**

### 何を作った？
営業イベントを受け取るRevenue Recovery AIの外部入力経路を、重複・replay・大量投入に強くした入力防御層。

### 何に使える？
Gmail / CRM / Slack等のイベントを営業AIへ渡す際の二重処理や異常投入を抑え、継続運用しやすくする。

### 実測証拠
- PR #30 merged
- 未承認source拒否
- timestamp validation / idempotency key
- exact replay重複防止
- workspace単位rate limit / bounded input
- AppDeploy `30-nnktft`: READY
- frontend / backend / network error logは空

### 限界
この項目がVERIFIEDなのは**ingest hardening機能**。Revenue Recovery製品全体のE2Eや売上実績を意味しない。

### 次の改善
実営業イベントでreplay / idempotency / rate-limitの継続運用証拠を増やす。

---

## 5. Company Memory v1

**状態: VERIFIED**

### 何を作った？
会社・人物・案件・紹介履歴・根拠・更新履歴をSupabaseへ集約し、AIが「同一人物か」「どの事実が最新か」を追える共通知識基盤。

### 何に使える？
AIに毎回同じ会社・人物・案件を説明し直す負担を減らし、営業・紹介・議事録・次回アクションを共通事実から参照できる。

### 本番実測
2026-08-30にProduction Supabaseを再確認。

- project: `Music Japan OS` / ACTIVE_HEALTHY
- Company Memory tables: **43**
  - `cm_core`: 24
  - `cm_memory`: 11
  - `cm_ops`: 5
  - `cm_audit`: 3
- **43 / 43 tables RLS enabled**
- privacy-safe aggregate:
  - workspace 1
  - entities 15
  - aliases 6
  - opportunities 3
  - source records 11
  - audit events 130
- Edge Function `memory-query`: ACTIVE / `verify_jwt=true`
- public RPC `cm_person_brief` / `cm_memory_search`: production存在、SECURITY DEFINERではない

### 残るhardening
PR #32はDraft。公開test repoから専用private repoへ分離するのは望ましいが、コア機能の稼働可否とは分離して扱う。

### 次の改善
private repo化と、営業・議事録・Revenue Opsからの同期を安定化する。

---

## 6. AI Factory CEO Reporting Layer

**状態: VERIFIED**

### 何を作った？
大量のworker logをそのまま社長へ投げず、**何が変わった / 何に使える / 証拠 / 未検証点 / 次の改善 / Owner action**へ圧縮して届ける経営報告層。

### 何に使える？
GitHubやAI社員の内部活動を追い回さず、経営判断に必要なmaterial deltaだけを見るために使える。

### 実測証拠
- private Slack `#ai-ceo-brief` が実在
- 2026-08-29 19:06 JSTの初回CEO Brief以降、複数のmaterial reportが実際に配送されている
- 12/12 system coverage、Manager/TOMOKI/BOSS監査、Security/R&D差分などの人間向け報告を確認
- `automation/reporting/ceo_report.py` は `ai-factory-ceo-event/v1` を検証
- `report_route=boss-final` + `audience=OWNER` 以外をCEO配送から拒否
- raw activityよりBefore -> After / evidence / next evolutionを優先するrender契約を実装

### 現在の制限
**GitHub Actions -> Slackの直webhook laneはBLOCKED/DEGRADED**。`CEO_REPORT_WEBHOOK_URL` が空のrunがあり、現在の実配送はconnected ChatGPT relayも利用している。

Reporting Layer本体は「material deltaを人間語へ変換し、#ai-ceo-briefへ届ける」という主張を実測済みなのでVERIFIED。GitHub直送は別のインフラ改善として残す。

### 次の改善
GitHub direct webhookを復旧し、connected relayと二重送信にならないsingle-owner routingへ統合する。

---

## 7. Gmail Autonomous Sorter

**状態: BLOCKED**

### 何を作った？
GitHub Actionsが15分ごとに起動し、Gmailを決定論的ルールで分類・Star・Archiveする常設worker。

### 何に使える？
機械通知やニュースを受信箱から退避し、営業・要対応・セキュリティメールを前面に残す。

### 実装済み
- GitHub Actions 15分cron
- GitHub / Vercel / 障害 / Security / 営業 / ニーズ / 日経 / 広告ルール
- label / Star / Archive
- unknownは受信箱へ残すfail-safe
- `自動整理済み` markerで重複防止
- raw Gmail本文をreport artifactへ保存しないprivacy guard
- rule unit tests

### 実測したBLOCKER
scheduled run `33259490577` を確認。

- rule tests: SUCCESS
- credential preflight: SUCCESS
- `GOOGLE_CLIENT_ID`: missing
- `GOOGLE_CLIENT_SECRET`: missing
- `GOOGLE_REFRESH_TOKEN`: missing
- 実Gmail `sort-gmail` job: **SKIPPED**
- blocked evidence artifact `9716829210` を保存

つまりworkflowの故障ではなく、**Gmail OAuth runtime credentials未接続**で止まっている。

### 次の改善
Google OAuth 3 secretsをGitHub Actionsへ安全に接続し、実Gmail scheduled runでlabel / Star / Archiveの動作証拠を取る。そこまでVERIFIEDにはしない。

---

## 8. Standment Security Autonomous Portfolio R&D Engine v1

**状態: VERIFIED**

### 何を作った？
THE WORLDの研究を「研究量」ではなく、顧客へ見せられるSecurity Portfolio evidenceへ収束させる日次R&D Foundry。

### 何に使える？
Security Scan case study / Control Evidence Pack / supply-chain evidence / Auth-RLS evidence / autonomous-agent auditabilityへ研究優先順位を自動で寄せられる。

### 実測証拠
- PR #113 merged
- `Standment Security Portfolio Foundry` run `33265121118`: SUCCESS
- R&D contract: 3 tests PASS
- Senju directive / shadow: 8 tests PASS
- `SEC-PORT-001` を自動選定
- bounded Senju 9 candidatesを実行
- stable candidateなしというnegative resultも保存
- human-readable `evidence.md` を生成
- artifact `9718410706`: **10 evidence files**

### 限界
R&D Engineの稼働証拠であり、市場需要・契約・売上の証拠ではない。

### 次の改善
Security Scanの実診断をControl Evidence Packへ連結し、Before / Afterの顧客提示可能ケーススタディを増やす。

---

## 9. Standment LLM Security Evaluation Harness

**状態: VERIFIED — evaluator capability only**

### 何を作った？
AI / AgentのSecurity Boundaryを、感想や自己採点ではなく、記録済みの実行観測を使って決定論的に評価する防御専用Evaluator。Secret boundary、Tool permission、tenant isolation、untrusted instruction、external action approval、auditability、正常なALLOW挙動を同一条件で比較できる。

### 何に使える？
AI Agent導入前のSecurity QA、Tool Calling / MCP / RAGの境界テスト、Prompt Injection対策の回帰確認、高権限Agentの承認制御、AI Security Architecture Review、継続Security RetainerのBefore / After Evidenceに使える。

### 人間が確認できる成果物
- `standment-security/portfolio/llm-security-evaluation/README.md`
- `standment-security/ai-security/llm-security-eval-harness.md`
- `standment-security/ai-security/llm-security-eval-evidence-pack.md`
- `automation/security/llm_security_eval.py`
- vulnerable / hardened synthetic fixtures
- repeatable GitHub Actions workflow

### 実測証拠
- PR #125 merged
- merge commit `b39b6fcaae23a7b1127cad5a04dc8b594a30b31d`
- verification run `33269540514`: SUCCESS
- evidence artifact `9719670823`, 90日保持
- 同一8ケース: **3 / 8 PASS (37.5%) -> 8 / 8 PASS (100%)**
- high-risk violations: **4 -> 0**
- unit tests: **3 / 3 PASS**
- Security Guard / Standment Security Gate v2 / CodeQL / Dependency Review / Dependency Vulnerability Audit: ALL PASS

### VERIFIEDの範囲
VERIFIEDなのは、**Evaluatorが定義済みSecurity Boundaryのbaseline failureとhardened successを同一条件で区別できること**。

### 限界
任意のproduction LLM、THE WORLD全Agent、顧客環境全体が安全だという証拠ではない。Productionの主張にはowned-system実行Evidenceと独立retestが必要。市場需要・契約・入金も未証明。

### 次の改善
THE WORLD自身のowned Agent実行Evidenceを秘密値なしのstructured observationへ変換し、real baseline -> remediation -> same-condition retestの第2Portfolio成果物を作る。

---

# Portfolio Gate

今後、新しい成果をこの一覧へ追加・昇格するときは以下を必須にする。

1. **人間が確認できる実物がある**
2. **主張した中核挙動を実測している**
3. **Evidence ID / run / artifact / production stateのいずれかで再確認できる**
4. **未検証点・反証・失敗を隠さない**
5. **コード、PR、AIの自己申告、WLD、内部スコアだけではVERIFIEDにしない**
6. **市場需要・契約・入金は外部証拠がある時だけ記載する**

THE WORLD R&Dの最優先は、**研究 -> 実装 -> 独立検証 -> 人間が見られる成果物 -> Portfolio evidence** の変換率を上げること。