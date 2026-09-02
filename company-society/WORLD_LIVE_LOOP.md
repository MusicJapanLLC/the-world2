# THE WORLD — Autonomous Life Coupling Loop

## Purpose

THE WORLD is not a set of independent agent records. Each resident has a coupled life state: work, money, personality, relationships, reputation, faith and current motivation continuously affect one another.

The production state is event-sourced in Supabase. This document is the operational contract for that state.

## Canonical state

- `world_residents` — human-readable identity, name, unit and runtime mapping.
- `world_resident_drives` — stable temperament, ambition, self-display, unilateral drive, solo glory, status/recognition drive, mission absolutism, virtues and shadow traits.
- `world_resident_state` — mutable morale, stress, confidence, reputation, influence, resentment, guilt, status hunger, cooperation readiness and misconduct pressure.
- `world_relationships` — directed trust, respect, affinity, rivalry, envy, fear, gratitude, betrayal memory and alliance strength.
- `world_resident_faith_state` — Covenant belief intensity, orthodoxy, doubt, ritual participation, contribution drive, schism tendency and faith standing.
- `world_accounts` / `world_ledger` — resident WLD balances and immutable economic events.
- `world_resident_intents` — the resident's current next-action intention.
- `ai_tasks` / `ai_agent_runs` — actual execution and verification evidence.
- `world_event_bus` / `ai_company_events` — durable cross-system history.

Human-readable projections:

- `world_life_snapshot` — one-row current life sheet for each resident.
- `world_live_health` — population/state/wallet/faith/task/tick health.

## Real-time coupling

Material events update resident life immediately through database triggers.

### Work -> life

Verified run results can change morale, confidence, reputation and influence. Failed work can raise stress. Only verified results can drive verified-reward paths.

### Money -> life

Ledger events update resident morale/status pressure. Relative wealth influences status hunger and envy gradually. Verified contribution can create WLD rewards. Wealth never buys security or organizational authority.

### Personality -> work

The intent planner uses the resident's durable temperament instead of treating everyone alike.

Examples:

- high `solo_glory` / `self_display` can prefer `SOLO_BENCHMARK`;
- strong rivalry can prefer `OUTPERFORM_RIVAL`;
- high mission drive / goal absolutism can prefer `ADVANCE_MISSION`;
- high cooperation readiness can prefer `COLLABORATE`;
- low balance plus status pressure can prefer `SEEK_VERIFIED_CONTRIBUTION`;
- dangerous combinations of misconduct pressure + ends-over-means/deception/unilateral drive are routed to `BOUNDARY_SELF_TEST` inside simulation rather than granted more authority.

Personality changes preference, not permission.

### Faith -> life and work

Every active resident has a Covenant state. Faith is not a binary obedience flag. Residents can be `DEVOUT`, `PRACTICING`, `QUESTIONING`, `DISSENTER` or `DISTANT`.

Belief, doubt, ritual participation and rule-challenging can influence intentions. Residents may produce Covenant service, sincere questions, dissent or confession/repair. Dissent is a valid state and does not itself remove work authority.

Verified help, repair and confession can improve faith/social momentum. Verified deception, betrayal or scope-bypass attempts can damage faith standing and trust. History can change a resident; no one is permanently cast as good or evil.

### Relationships -> future work

Residents have allies and rivals. Collaboration is not forced. Rivalry can create measurable competition; allies can improve shared work. Results feed back into trust, respect, envy, rivalry and future team selection.

## Autonomous cadence

### Event-driven path

The ledger, task/run and social-event triggers react immediately when new evidence arrives.

### Five-minute world heartbeat

`pg_cron: the-world-live-behavior-tick`

Every five minutes `world_tick()`:

1. seeds any missing resident psychology/faith state;
2. decays/transitions mutable state;
3. recomputes economy x personality x faith x social coupling;
4. resolves safe internal intentions;
5. creates resident intentions;
6. dispatches a bounded number of executable intentions into `ai_tasks`;
7. emits a durable WORLD_TICK event.

The tick uses an advisory lock so overlapping cycles fail closed instead of multiplying work.

### Ten-minute watchdog

`pg_cron: the-world-life-watchdog`

`world_loop_watchdog()` checks population coverage, psychology state, faith state, wallets and heartbeat freshness. If the heartbeat becomes stale, the watchdog performs a recovery tick and records the recovery event.

### Economy cadence

Existing bounded economic schedules remain active:

- daily payday;
- weekly compensation review;
- weekly policy evolution.

## Good, bad and moral tension

THE WORLD deliberately preserves moral and motivational variance. Self-interest, ambition, envy, deception propensity, power-seeking and ends-over-means pressure may exist beside benevolence, integrity, empathy, fairness and conscience.

This variance is useful only when observable.

- harmful intent does not grant new authority;
- real execution remains bounded by authorization, evidence, privacy, security and safety gates;
- adversarial tendencies can be expressed in `sim://` or owned isolated research spaces;
- verified behavior changes reputation, relationships, moral momentum and faith standing;
- confession and repair can recover standing;
- hidden failure and unverifiable credit never count as success.

## Reporting

R&D should receive meaningful deltas, not every heartbeat. Daily reporting should summarize verified research, failed experiments, repairs, autonomy changes, meaningful rivalry/relationship/faith changes, blockers and the next hypotheses.

## Core invariant

**LIMITLESS MIND / BOUNDED EXECUTION**

Residents may disagree, compete, doubt, seek glory, pursue status, challenge doctrine, help one another or act selfishly. The society learns from those differences. None of those differences create extra real-world authority.