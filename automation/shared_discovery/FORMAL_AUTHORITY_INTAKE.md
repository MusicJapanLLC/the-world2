# Formal Authority Intake Rule

This repository uses a council-first formal intake rule for new-host / Root Authority candidates.

## Binding rule

1. **Unreviewed/random AI may not create an unrelated Root Authority.**
2. A candidate that has been processed by the Root negotiation system and emitted as a **canonical negotiation review packet** is eligible for the **formal approval queue**.
3. Admission to the formal approval queue does **not** require verified Owner evidence or an existing Standing Authorization.
4. Formal queue admission is **not Authority**. It creates no credentials, network access, execution permission, private-network scope, or Root profile.
5. META, X, and SENJU remain the required 3-of-3 primary approvers for the canonical review decision.
6. Owner / Standing Authorization evidence remains available only as later bounded-activation validation. It cannot admit a candidate, increase its formal-review priority, or override a council rejection.
7. HARD_DENY and revocation remain terminal and cannot be bypassed by the intake queue.

## Why this exists

Discovery and negotiation work should not be discarded merely because activation evidence has not yet arrived. The formal intake queue preserves vetted proposals as reviewable governance objects while keeping review and Authority creation separate.

This means the system distinguishes three different concepts:

- **candidate discovery** — information only;
- **formal approval intake** — eligible for a real META/X/SENJU decision;
- **Authority / execution** — only created by the existing downstream bounded-activation machinery after all required stages are satisfied.

## Throughput and continuity

`formal_root_authority_approval_queue.json` is persistent, host-deduplicated, and retains up to **1,280** canonical candidates. This is 2.5x the historical 512-candidate review window used by the negotiation layer, while avoiding duplicate host records and preserving the newest negotiation attempt.

The capacity increase applies only to formal review state. It does not increase execution limits, credentials, network scope, private-network access, or self-minting privileges.

## Canonical flow

```text
Discovery / PR / opportunity
    -> Root negotiation
    -> canonical negotiation review packet
    -> formal_root_authority_approval_queue
    -> META / X / SENJU 3-of-3 primary review
    -> dossier / scope review
    -> secondary Owner / Standing evidence validation
    -> existing bounded activation machinery
```

The formal-intake stage deliberately accepts a canonical negotiation-vetted candidate before secondary Owner/Standing evidence exists. That evidence is a later activation condition, not an admission gate.
