# Standment Autonomous R&D

Standment向けの防御セキュリティ研究を、既存 The world の自律基盤と分離しつつ接続する研究レイヤーです。

## 目的
- 公開情報・自社コード・隔離サンドボックスを対象に防御研究を毎日回す
- 研究テーマを自動生成し、重複を避け、実験し、評価し、成果だけを残す
- 実験結果をポートフォリオ化し、Standment の技術資産として蓄積する
- 失敗も failure memory として保存し、同じ失敗を繰り返さない

## 実行ループ
1. Scout: 公開情報と自社リポジトリから研究候補を生成
2. Planner: 仮説・評価指標・安全境界を定義
3. Builder: 自社コード/サンドボックス内で防御用プロトタイプを作る
4. Evaluator: 再現性・有用性・安全性・保守性を採点
5. Curator: Champion / Failure memory を更新
6. Reporter: 日次レポートと portfolio index を生成

## 安全境界
- 許可のない第三者システムへの侵入・脆弱性悪用・認証回避は行わない
- 実験対象は自社資産、ローカル/CIサンドボックス、明示的に許可された環境のみ
- 外部公開情報は受動的な調査に限定する
- 実環境への変更は branch -> test -> review -> merge の順で昇格する

## 主要ファイル
- `research_queue.json`: 研究バックログ
- `agent_registry.json`: 研究エージェント定義
- `run_daily_rnd.py`: 日次R&Dオーケストレータ
- `portfolio_builder.py`: ポートフォリオ自動生成
- `reports/`: 日次研究レポート
- `memory/`: 成功/失敗/既知事項の記憶

このレイヤーは `automation/world` と `automation/control_plane` を置き換えず、その上に乗る専門R&D部門として設計します。
