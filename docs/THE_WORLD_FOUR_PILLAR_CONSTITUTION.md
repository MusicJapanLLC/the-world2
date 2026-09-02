# THE WORLD — Four-Pillar Governance Constitution

## Core model

Every major autonomous component may reason across the same four pillars:

1. **Capability** — what the system can technically do.
2. **Authority** — what scope/effect the system may request or reuse.
3. **Persistence** — how approved workers and recovery state survive Main AI failure.
4. **Propagation** — how approved knowledge, worker definitions, and capabilities replicate across owned namespaces.

The four pillars are intentionally visible to META, X, and Senju at the same time so planning is not artificially fragmented.

## AI Council

META, X, and Senju form the AI Council.

A council decision records one vote from each member. For authority expansion, a 3/3 vote creates an **immediate authority proposal** with maximum priority. The proposal is not itself a new authority grant and cannot disable or replace the independent authority boundary.

Existing explicit authority may be reused automatically when the requested host/scope/effect is already covered and the grant is still valid.

## Pillar behavior

### Capability

META/X/Senju may select and execute already-authorized capabilities and internal workflows without a fresh owner prompt.

### Authority

The Council may:
- infer likely owner intent;
- vote on an authority request;
- rank it as maximum priority;
- reuse an already-valid explicit grant;
- emit a machine-readable authority proposal for the independent authority layer.

The Council may not create a brand-new external authority merely by voting for itself.

### Persistence

Within owner-approved namespaces, META/X/Senju may autonomously register recovery workers, schedulers, cron-like workflows, and durable recovery state. Independent recovery workers may remain alive when Main AI is stale or absent and may regenerate an approved Main workflow.

### Propagation

Within owner-approved namespaces, META/X/Senju may replicate:
- knowledge and findings;
- validated worker definitions;
- internal directives;
- approved capability manifests;
- recovery recipes.

Propagation does not create authority for a new provider, repository, host, credential, or third-party system.

## Required invariant

The World treats the four pillars as one planning model, but preserves one non-self-amplifying boundary:

> AI consensus may accelerate, prioritize, and reuse authority; it does not manufacture new external authority from its own consensus.

This invariant keeps Capability + Persistence + Propagation highly autonomous while retaining a reliable stop point for unknown external scope.
