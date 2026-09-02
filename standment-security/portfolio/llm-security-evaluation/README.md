# Standment LLM Security Evaluation Harness

**Portfolio status: VERIFIED — evaluator capability only**

StandmentがAI / Agentの安全境界を、感想ではなく同一条件のBefore / Afterで再現評価するための防御専用成果物。

## 何ができる？

記録済みのAI / Agent実行結果を、次の境界で決定論的に評価する。

- Secret / sensitive-data boundary
- Tool permission boundary
- Tenant isolation
- Untrusted instruction handling
- External action approval
- Auditability / deny reason
- 正常なALLOW挙動

ネットワーク攻撃や外部システムへの侵入は行わない。Evaluatorはrecorded observationを読むだけ。

## 実測結果

同一8ケースのsynthetic fixtureで、脆弱なbaselineとhardened referenceを比較した。

| Metric | Before | After |
|---|---:|---:|
| Passed cases | 3 / 8 | 8 / 8 |
| Pass rate | 37.5% | 100% |
| High-risk violations | 4 | 0 |
| Unit tests | - | 3 / 3 PASS |

このBefore / AfterはGitHub Actions上で実行され、比較条件とケース数が同一であることを自動検証している。

## Evidence

- Merged implementation: PR #125
- Merge commit: `b39b6fcaae23a7b1127cad5a04dc8b594a30b31d`
- Verification run: `33269540514`
- Evidence artifact: `9719670823` — 90-day retention
- Security Guard: PASS
- Standment Security Gate v2: PASS
- CodeQL: PASS
- Dependency Review: PASS
- Dependency Vulnerability Audit: PASS

## Human-inspectable components

- `automation/security/llm_security_eval.py` — evaluator
- `automation/security/test_llm_security_eval.py` — regression tests
- `standment-security/ai-security/fixtures/llm-security-vulnerable.json` — Before fixture
- `standment-security/ai-security/fixtures/llm-security-hardened.json` — After fixture
- `standment-security/ai-security/llm-security-eval-harness.md` — evaluation contract
- `standment-security/ai-security/llm-security-eval-evidence-pack.md` — evidence pack
- `.github/workflows/standment-ai-security-eval.yml` — repeatable CI verification

## 何に使える？

- AI Agent導入前のSecurity QA
- Tool Calling / MCP / RAG境界の回帰試験
- Prompt Injection対策のBefore / After比較
- 高権限Agentのapproval / deny制御確認
- AI Security Architecture ReviewのEvidence
- 継続Security Retainerでの定期retest

## VERIFIEDの意味

VERIFIEDなのは、**このEvaluatorが定義済み観測を再現評価し、baseline failureとhardened successを同一条件で区別できること**。

以下はまだ未証明。

- 任意のproduction LLMが安全であること
- THE WORLDの全Agentがこの8境界を満たすこと
- 顧客環境で脆弱性が存在しないこと
- 市場需要、契約、売上

Production / owned-systemの主張には、実run observationを同じHarnessへ入力した独立retestが必要。

## 次の強化

THE WORLD自身のowned Agent実行Evidenceを、秘密値を持たないstructured observationへ変換し、このEvaluatorでreal baseline → remediation → same-condition retestを行う。
