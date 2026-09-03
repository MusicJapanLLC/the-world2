# Autonomous Codegen Loop

自律的にコードを生成→テスト→フィードバック→再生成するシステム。

## 仕組み

```
tasks/*.json  →  loop.py  →  generated/*.py  →  pytest
                    ↑                               |
                    └─────── runs/iter_N.json ←─────┘
                           (失敗時: 前回コード+エラー出力をフィードバック)
```

1. `tasks/` にタスク仕様(JSON)を置く
2. `loop.py` が Claude API を呼んでコードを生成
3. `test_cmd` でテスト実行
4. 失敗したら直前の失敗コード+エラーをプロンプトに載せて再生成
5. `runs/` に各イテレーション結果を蓄積

## タスク仕様フォーマット

```json
{
  "name": "人間が読む名前",
  "goal": "何を実装するか（自然言語で詳細に）",
  "output_file": "生成コードの出力先パス（リポジトリルートからの相対）",
  "test_cmd": "pytest tests/test_xxx.py -v",
  "constraints": "stdlib のみ, O(n log n) 以内, など"
}
```

## ローカル実行

```bash
export ANTHROPIC_API_KEY=sk-...
pip install anthropic pytest
python automation/codegen/loop.py example 10
```

## GitHub Actions から実行

Actions タブ → **Autonomous Codegen Loop** → Run workflow → task_id を入力

`repository_dispatch` でも起動可能:

```bash
curl -X POST https://api.github.com/repos/OWNER/REPO/dispatches \
  -H "Authorization: token $GH_TOKEN" \
  -d '{"event_type":"run-codegen","client_payload":{"task_id":"example","max_iterations":"5"}}'
```

## 新しいタスクを追加する手順

1. `automation/codegen/tasks/my_task.json` を作成
2. `automation/codegen/tests/test_my_task.py` にテストを書く
3. Actions から `task_id=my_task` で実行

結果は `automation/codegen/runs/my_task/iter_NNN.json` に蓄積される。
