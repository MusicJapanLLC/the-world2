# AI Foundry Failure / Learning Memory v4

Status: BUILDING / runtime evidence required

## Purpose

Prevent the AI development loop from repeatedly spending candidate budget on the same rejected mutation family while preserving the ability to retry an idea when genuinely new passing evidence appears.

## Runtime contract

The Foundry now keeps a bounded negative-evidence memory for rejected candidate families.

- A mutation family is identified by a stable fingerprint derived from the changed parameter dimensions and directions, not the exact sampled numeric values.
- Repeated rejected families are deprioritized after the recurrence threshold is reached.
- The engine resamples a bounded number of times rather than looping indefinitely.
- Memory is capped and expires after a bounded generation horizon.
- A historically rejected family can be superseded when fresh evidence passes every currently authoritative gate.
- Security, permission, correctness, visible-fixture, holdout and regression gates remain authoritative. Memory cannot waive them.

## Current bounds

- maximum retained entries: 128
- recurrence threshold: 2 rejected observations
- resample attempts: 4 per candidate slot
- expiry horizon: 720 generations

These are engineering defaults, not claims of optimality. Future changes require the same regression and holdout discipline as other Foundry parameters.

## Evidence emitted

The hourly source pack must expose enough information to distinguish learning from activity:

- current active failure-memory entries
- failures recorded in the current run
- repeated-family candidates avoided
- historical failures superseded by fresh passing evidence
- expired entries
- representative high-recurrence fingerprints

A lower number of repeated candidates is useful only when the Foundry continues to discover eligible alternatives. Avoidance without useful exploration is not considered progress.

## Promotion evidence

This capability must not be described as VERIFIED merely because the source file or tests exist. Promotion requires runtime evidence showing, under reproducible conditions:

1. the same rejected family recurs and reaches the configured threshold;
2. a later candidate from that family is actually resampled/avoided;
3. bounded resampling still yields useful exploration rather than deadlock;
4. expiry removes stale negative evidence;
5. fresh passing evidence can supersede an old failure without bypassing any gate;
6. the run artifact preserves the relevant counters/fingerprints for independent inspection.

## Claim boundary

This is engineering-process memory for THE WORLD's AI development loop. It is not model-weight training, consciousness, permanent human-like memory, customer validation, or proof that the resulting AI system is secure.
