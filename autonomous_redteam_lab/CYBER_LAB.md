# Autonomous Red Team Lab

診断結果を入力し、**攻撃者目線の仮説 → 安全な確認 → 証拠整理 → 修正優先度判断**を自動で回すローカル専用ラボです。

## 設計

これは実サービスへ侵入する自律攻撃機ではありません。コード側で以下を強制します。

- ターゲットは `localhost` / loopback / private IP / link-local のみ
- 公開IPへ解決されるURLは実行拒否
- 1回の実行で最大12リクエスト
- GET / HEAD / OPTIONS / 限定POSTのみ
- パスワード総当たりなし
- 認証回避なし
- exploit payload実行なし
- path fuzzingなし
- データ変更なし
- phishing送信なし

その代わり、診断結果から「攻撃者なら次に何を見るか」を自動展開し、無害な確認だけを実行します。

```text
Findings JSON
   ↓
Attack Hypothesis Planner
   ↓
Policy Guard ── 公開IPなら即停止
   ↓
Safe Validator
   ├─ baseline headers
   ├─ GraphQL: query { __typename }
   └─ security.txt
   ↓
Evidence Analyzer
   ↓
Markdown + JSON report
```

## 実行

```bash
cd autonomous_redteam_lab
python -m cyber_lab.core \
  --target http://127.0.0.1:3000 \
  --findings examples/findings.json \
  --out redteam-report.md \
  --json-out redteam-report.json
```

## 今回のFindingで展開する仮説

- GraphQL認証・認可境界
- GraphQL情報露出
- Cookie HttpOnly + XSS連鎖
- Serverヘッダーによる技術推測
- Permissions-Policy
- security.txt
- SPF/DMARC
- 公開管理面

### `/graphql` の扱い

認証突破はしません。代わりに無害な `query { __typename }` だけ確認します。

- HTTP 401 → 認証境界あり
- HTTP 200 → 無害queryは通るためresolver認可・schema公開方針をレビュー

## GitHubでの自律化

`findings.json` 更新 → CIテスト → ラボ実行 → Markdown/JSONレポート → FindingごとのIssue化、という流れへ拡張可能です。
