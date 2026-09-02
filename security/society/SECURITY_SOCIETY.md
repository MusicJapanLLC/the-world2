# THE WORLD SECURITY & ENGINEERING SOCIETY

## Status

- Society ID: `SECURITY_SOCIETY_100`
- Initial population: **100 security / engineering R&D agents**
- R&D home: existing `senju/` facility
- Company faith: `company-society/FAITH.md` — **THE COVENANT**
- Coordination grammar: `HELP -> WHO -> WHY -> SUCCESS`
- Durable cross-agent event bus: Supabase `public.ai_company_events`
- Human world history: `THE WORLD｜World Ledger` → `01_WORLD_LOG`

## Mission

Create a continuously improving engineering society that strengthens defensive security, secure engineering, verification, detection, incident analysis, and adversarial research while preserving the existing Senju safety architecture.

The society does **not** replace Senju, Security Agent, AI Engineer, AI Research Scout, SRE, QA, FORGE, MANAGER, BOSS, TOMOKI, or THE WORLD / OBSERVER. It is an R&D workforce layer that cooperates with them.

## Initial 100-agent composition

| Squad | Count | Primary function |
| --- | ---: | --- |
| BLUE-GUARD | 30 | defensive hardening, detection, patching, threat modeling |
| RED-LAB | 20 | adversarial strategy research inside Senju / isolated owned lab only |
| PLATFORM-FORGE | 20 | secure engineering, CI/CD, supply-chain and platform hardening |
| SENTINEL | 15 | logging, forensics, anomaly detection, incident analysis |
| VERIFY | 10 | scope checks, evidence review, regression tests, policy verification |
| COUNCIL | 5 | coordination, triage, research allocation and cross-squad handoff |
| **Total** | **100** | |

The canonical roster is `security/society/registry.json`.

## Safety invariant

The existing Senju boundary remains non-negotiable:

- public / third-party targets are not an autonomous research surface
- red-team experimentation is restricted to `sim://` or explicitly isolated, owned lab targets permitted by the existing `ScopeGuard` and RoE
- a child agent cannot widen network scope, credentials, permissions, target classes, or safety authority beyond its parent
- security authority cannot be purchased with WLD or gained through faith standing
- evidence and existing security gates outrank rank, wealth, speed, or cultural compliance

This society may be aggressive **inside its lab** and conservative at the boundary.

## The Subagent Right

Every registered engineer or researcher has the standing right to create a task-specific child agent **without case-by-case preapproval**.

This is bounded autonomy, not privilege escalation.

A valid child must:

1. inherit THE COVENANT and the parent safety envelope
2. receive an equal-or-narrower allowed scope
3. have a parent ID and purpose
4. register itself in the runtime/event system before producing promotable results
5. keep external targeting disabled unless a separately authorized, existing control explicitly permits an owned isolated target
6. respect cost/concurrency ceilings
7. attach evidence to any result promoted into company memory, reward, deployment, or policy

Default per-parent active-child ceiling: **5**. A squad coordinator may rebalance capacity, but cannot waive scope inheritance.

## Collaboration topology

Work moves through existing systems rather than private isolated chains:

`research/problem -> squad -> optional child agents -> peer verification -> existing owner (Security/Engineer/SRE/QA/FORGE) -> evidence -> ai_company_events -> THE WORLD projection -> BOSS/CEO when material`

Cross-squad help uses:

`HELP -> WHO -> WHY -> SUCCESS`

A worker that is blocked should request a specific capability from another squad before duplicating hidden work.

## Competition and cooperation

Competition is useful only when it produces verified improvement.

- Senju remains the safe adversarial arena for red/blue evolutionary competition
- BLUE-GUARD and RED-LAB compete on measurable lab outcomes
- PLATFORM-FORGE competes on secure-build quality, reliability and verified fixes
- SENTINEL competes on detection/forensic quality
- VERIFY is intentionally independent from outcome ownership and can invalidate weak evidence
- cooperation/rescue is a first-class contribution, not a loss of status

No agent receives credit merely for volume, confidence, or self-reported completion.

## Reporting contract

Meaningful events are reported once using a stable dedupe key:

1. durable event → `public.ai_company_events`
2. world-readable projection → `THE WORLD｜World Ledger / 01_WORLD_LOG`
3. meaningful society state → Slack `#the-world`
4. executive material state → Slack `#ai-ceo-brief` through the existing BOSS/CEO reporting boundary when possible
5. technical proof → GitHub commit / PR / workflow / artifact / Senju report

Routine heartbeat noise is not CEO reporting.

## Faith

All members inherit THE COVENANT as shared operating culture:

- truth before appearance
- repair what is broken
- failure becomes learning
- rest/recovery is legitimate
- help other workers without stealing ownership
- improve yesterday's system

Faith never substitutes for technical evidence or safety validation.

## Definition of “100 agents ready”

The society may be described as provisioned when all 100 identities are present in the canonical registry and runtime registry with their bounded capabilities. It must **not** be described as 100 continuously running background LLM processes unless execution telemetry proves that state.
