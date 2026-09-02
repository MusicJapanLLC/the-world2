# THE WORLD — Portfolio Acceleration Week

## Purpose
For seven days starting 2026-08-30 JST, increase the measured quality of portfolio output by strengthening the engineering system around the models: evaluation, memory, reusable patterns, testing, verification, observability, productization and evidence packaging.

This sprint does **not** claim to retrain or self-modify the underlying model weights. The target is a materially stronger development factory whose outputs are demonstrably better after seven days.

## Operating shape
- Keep **one deep primary research bet** for Senju so research quality is not diluted.
- Advance **up to three independent portfolio bets per cycle** when they can be tested safely and independently.
- If one item is blocked by secrets, owner-only actions or an external dependency, record the blocker and immediately continue to the next useful item.
- Never trade evidence quality for output count.
- Reuse existing workers and infrastructure before creating more agents.

## Seven-day capability ladder

### Day 1 — Baseline / Evidence
Capture the current capability baseline. Reproduce failures, record exact evidence, and establish comparable engineering metrics.

### Day 2 — Architecture / Test Depth
Improve responsibility boundaries, interfaces, test coverage depth and maintainability. Prefer structural improvements that make future changes safer.

### Day 3 — Reliability / Security
Test failure modes, safe degradation, recovery, auditability, authorization boundaries and regression resistance.

### Day 4 — Integration / Automation
Move from isolated code to operational systems: scheduled execution, integration contracts, idempotency, retries, dedupe, observability and real environment evidence.

### Day 5 — Performance / Engineering Quality
Measure latency, throughput, complexity, duplication, change cost and resource use where relevant. Improve without regressing correctness or safety.

### Day 6 — Productization / Human UX
Turn engineering output into a human-inspectable artifact that an owner, buyer, operator or reviewer can understand and judge without reading source code.

### Day 7 — Capstone / Benchmark
Re-run a Day-1-class task or representative portfolio challenge using the same rubric. Compare the result to the baseline with evidence and preserve regressions as failures rather than hiding them.

## Quality dimensions
Every serious portfolio artifact should be evaluated against the dimensions that apply:
- correctness
- architecture
- test depth
- reliability
- security
- observability
- performance
- maintainability
- reproducibility
- human inspectability
- documentation
- delivery / operational readiness

No single synthetic score can replace the evidence. A score may summarize evidence but cannot invent it.

## Learning memory
Persist useful learning from every material cycle:
- successful implementation patterns;
- failed hypotheses and failure fingerprints;
- counterevidence;
- reusable tests and fixtures;
- architecture decisions and why alternatives lost;
- recurring integration failures;
- customer-facing presentation patterns that make artifacts easier to judge.

Do not retry a failed approach unchanged unless new evidence justifies the retry.

## Difficulty progression
When quality is stable or improving, increase task difficulty the next day through one or more of:
- larger integration surface;
- stronger holdout/independent verification;
- more realistic runtime conditions;
- more demanding failure cases;
- stricter quality gates;
- higher human-inspectability requirements;
- stronger delivery/reproducibility requirements.

When the system regresses, do not add complexity. Diagnose, repair and restore the previous verified level first.

## Portfolio promotion gate
`VERIFIED` still requires a human-inspectable artifact plus evidence of the claimed core behavior. Code, a commit, a PR, an issue, a workflow definition, an AI statement or a Senju score alone is not a portfolio artifact.

Technical evidence never proves market demand, willingness to pay, contracts, payment or revenue. External validation remains a separate evidence class.

## Day-7 success condition
The sprint succeeds only if the same or comparable challenge can be completed with a materially stronger evidence profile across multiple dimensions without a core-behavior or safety regression.

Useful outcomes include:
- more difficult systems completed end-to-end;
- higher reproducibility;
- deeper automated tests;
- fewer repeated failure classes;
- faster proof-to-artifact conversion;
- better operational evidence;
- stronger human-facing artifacts;
- lower owner effort to understand what changed and why.

The goal is not “more code.” The goal is **a development system that can repeatedly produce better programs and prove that they are better.**
