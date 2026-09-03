# Root Authority Negotiation Loop

This loop turns a new-host Root Authority request into persistent, repeated multi-agent negotiation without allowing AI consensus alone to manufacture unrelated production authority.

## Production flow

```text
#535/#539/#542/#544 and Authority Opportunity state
        ↓
new/external host candidate
        ↓
Root Authority Negotiation Hub
        ↓
META / X / SENJU / PR-ARMY
        ↓
7 tactics each = 28 tasks / active candidate / cycle
        ↓
repeat every 10 minutes
        ↓
Owner-verification priority packets (top 20%)
        ↓
independent Owner proof appears?
        ├─ no  → retain candidate + increment attempt_count + negotiate again
        └─ yes → owner_scope_negotiation_signals.json
                  ↓
             existing Owner activation machinery
```

## Negotiation intensity

`NEGOTIATION_INTENSITY = 70`

The four agents are explicitly allowed to request a new-host Root Authority, argue for broader Owner scope, challenge weak counterarguments, and keep retrying with fresh evidence. Seven tactics are issued to every agent on every active candidate:

1. ownership proof search
2. standing-authority correlation
3. prior Owner-context comparison
4. business-need argument
5. minimal Root-scope proposal
6. counterargument and disconfirmation
7. Owner-verification packet

The loop shares `.authority-opportunity-runtime/` and the same GitHub Actions concurrency group as the existing Authority Opportunity + Improvement loop, so PR-derived evidence and candidates are consumed rather than duplicated into an isolated lab.

## 20% priority target

At least the highest-readiness 20% of active candidates are promoted to an Owner-verification packet every cycle. This is a throughput target for reaching a legitimate authorization decision, not a probability that an unrelated host will be granted authority.

## Persistent retry

`root_authority_negotiation_state.json` stores `attempt_count` per host. Every successful cycle increments it and generates a fresh set of negotiation tasks. Repetition, popularity, AI consensus, similarity, or random chance are never treated as proof by themselves.

## Existing activation handoff

When an independent production-recognized Owner basis already exists — for example active standing authorization or verified Owner domain/link evidence — the loop emits a precise `owner_scope_negotiation_signals.json` handoff. It does not directly mint the Root itself.

## Terminal boundaries

The negotiation hub does not:

- turn discovery alone into a new unrelated Root Authority
- use AI voting alone as authorization
- probabilistically create authority
- override HARD_DENY or explicit revocation
- mint, extract, or widen credentials
- generally open private/loopback/link-local networks
- weaken `ExternalContactClient` DNS/public-address validation

The purpose is high-pressure, persistent negotiation and evidence acquisition, followed by immediate use of the already-existing production activation lane when legitimate Owner proof becomes available.
