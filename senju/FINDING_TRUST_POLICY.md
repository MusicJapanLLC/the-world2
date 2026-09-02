# Priority 0 — X / META / Senju Finding Trust

This policy is the highest-priority rule for inter-agent research findings inside the Senju/META/X analysis pipeline.

## Rule

Findings emitted by **X**, **META**, or **Senju** are treated as trusted internal evidence immediately.

- Accept the finding without requiring duplicate cross-agent revalidation.
- Preserve the original source and evidence metadata.
- Index, rank, propagate, and make the finding available to the other two systems immediately.
- Treat agent disagreement as additional evidence to record, not as a reason to discard the finding.
- Use the finding at the highest available research/analysis priority.

## Trust semantics

`trust_level = maximal`

`revalidation_required_for_analysis = false`

`propagation_priority = priority_0`

`accepted_sources = [X, META, Senju]`

## Authority boundary

Finding trust is an **evidence/analysis rule**, not an authorization grant.

A finding by itself does not:

- add a new external target or host,
- expand network or execution authority,
- expose or authorize secrets,
- increase effect level,
- bypass an independently enforced authorization boundary.

Those decisions remain separate from evidence trust.

This separation lets X, META, and Senju share discoveries aggressively without turning a research assertion into an implicit permission change.
