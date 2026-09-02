# Senju AI Advisor Policy

Senju has two standing AI development resources:

- Standment Personal AI Core: https://standment-personal-ai-core-se1c3z.v2.appdeploy.ai/
- AI FOUNDRY Forge V2: https://test-git-feat-ai-foundry-forge-v2-musicjapanllc.vercel.app/

## Standing rule

1. **Senju may ask these AIs any question.** There is no topic/category allowlist in the advisor rule. A question does not have to be limited to the current simulator, software engineering, or security.
2. Questions may cover architecture, algorithms, agent behavior, research, testing, reliability, observability, UX, developer tooling, performance, maintainability, product design, business ideas, philosophy, outside knowledge, or any other subject Senju judges useful or interesting.
3. **Advisor answers may be implemented.** When an answer contains a concrete improvement for Senju or an owner-controlled development resource, Senju may promote it into the existing implementation lane without waiting for a new question that repeats the same instruction.
4. Advice is input, not proof. A recommendation is not treated as implemented, tested, deployed, or successful until there is execution evidence.
5. Preferred implementation path:

   `question -> Personal AI Core -> AI FOUNDRY synthesis -> Repo Engineer patch -> sandbox tests/repair -> pull request -> review/merge`

6. The advisor answer itself is not executed verbatim as shell/code and does not create new credentials, network authority, target ownership, or deployment authority. The implementation executor uses whatever authority its existing lane already has.
7. Keep automatic changes focused and evidence-backed. Inspect current repository state and active PR overlap before editing, then test the resulting change and preserve the run/PR evidence.
8. If one advisor is unavailable, preserve the failure as evidence and continue where a useful answer is still available. Do not fabricate an answer or success state.
9. Advisor failures, recommendations, implementation decisions, tests, repair results, and pull-request URLs are evidence and should be preserved in the evolution artifacts and owner report.

## Role split

### Standment Personal AI Core

Primary role: broad senior advisor and second opinion.

Use it actively. Ask whatever Senju wants to know, challenge assumptions, explore ideas, propose improvements, identify weak spots, suggest experiments, and produce implementation-oriented recommendations when appropriate.

### AI FOUNDRY Forge V2

Primary role: implementation-oriented engineering peer and synthesis layer.

Use the user-specified public FOUNDRY deployment at `/api/foundry`. It receives the current question, Senju context, and Personal AI Core answer, then decides whether there is a focused implementation candidate. When there is, the existing Repo Engineer and repair/test lane performs the code change and produces a reviewable PR.

## Evidence standard

The following labels are distinct:

- **ADVISED** — an AI recommended it.
- **PLANNED** — Senju selected it as an implementation candidate.
- **PATCHED** — code was actually changed in the worktree.
- **VERIFIED** — relevant tests completed successfully.
- **PR OPENED** — a reviewable branch and pull request were created.
- **MERGED/DEPLOYED** — only after the corresponding GitHub/deployment evidence exists.

Do not collapse these states into one claim.
