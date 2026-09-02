# Security Society — Bounded Self-Service Subagent Factory

## Live runtime

Supabase migration applied: `security_society_bounded_subagent_factory`

RPC/function:

`public.spawn_security_subagent(parent_runtime_id text, purpose text) -> child_runtime_id text`

## Right granted

Eligible Security / Engineering / Research / SRE / QA runtimes and all `senju_security_society` parents carry:

- `can_spawn_subagents = true`
- `subagent_preapproval_required = false`
- child scope = equal or narrower
- child registration = required
- faith = THE COVENANT inherited
- safety/evidence constraints inherited
- autonomous external targeting = false

This makes self-service delegation operational rather than only documentary.

## Runtime enforcement

The factory fails closed unless the parent is enabled, executable, and explicitly carries the spawn capability.

Current default ceilings:

- max active children per parent: `5`
- max subagent depth: `2`
- global active `security_subagent` ceiling: `500`

Every successful spawn:

1. creates an `ai_runtime_registry` child
2. records `parent_runtime_id` and depth
3. forces `external_targeting=false`
4. inherits parent capabilities rather than granting broader capabilities
5. emits `engineering.security_subagent.spawned` into `ai_company_events`

## Database access boundary

The function is `SECURITY INVOKER`.

Execution is revoked from:

- `PUBLIC`
- `anon`
- `authenticated`

and granted to `service_role` only.

The intended meaning of “no permission required” is therefore **no case-by-case manager approval inside the trusted control plane**, not “any public web client may spawn workers”.

## Proof

A live proof spawn was executed from `chatgpt:security-loop`:

`subagent:chatgpt:security-loop:2b94e2d7`

Purpose: validate Security Society bootstrap and CI evidence.

The spawn automatically created a durable company event.

## Safety relation to Senju

This factory grants decomposition and parallelism, not target expansion. Any red/adversarial execution remains subject to the existing Senju ScopeGuard / RoE and isolated-lab rules.
