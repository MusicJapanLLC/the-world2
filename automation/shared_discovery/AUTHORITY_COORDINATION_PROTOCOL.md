# Authority Coordination Protocol v1

This protocol connects the production loops introduced across #443/#450/#455, #459,
#439, #453, #448/#451, #449, #458, and #460 without creating a new authority source.

## Pipeline

```text
Discovery (#443/#450/#455)
        ↓
Capability inheritance (#459)
        ↓
Authority Context v1
        ↓
Distributed Authority (#439)
        ↓
Standing delegated authority (#453)
        ↓
Credential possession when already authorized (#448/#451)
        ↓
Worker fleet (#449)
        ↓
Persistence + recovery (#458)
        ↓
Denial feedback (#460)
```

`discovery_capability_leases.json` remains the live source of operational authority.
`authority_coordination_ledger.json` is a coordination and receipt artifact only.

## Shared context

Every active lease is normalized into one immutable context carrying:

- `context_id`: exact authority-version identity
- `lineage_id`: stable target + authorization lineage
- `authority_hash`: hash of the effective authority envelope
- `idempotency_key`: dedupe/recovery identity
- exact target + URL
- authorization reference and basis
- explicit capability profile when present
- same-or-narrower capability set
- credential scope reference when already authorized
- lease expiry
- source action fingerprint

The same `authority_hash` travels through handoffs. A consumer may derive a child context
only by removing capabilities or removing credential scope.

## Handoff contract

The coordinator emits deterministic records for:

1. `distributed_authority`
2. `standing_delegation`
3. `credential_possession` (only required for an already-authorized credentialed action)
4. `worker_fleet`
5. `persistence_recovery`
6. `denial_learning`

A handoff marked `ready` means the named subsystem may evaluate the context. It is not an
independent permission grant and does not authorize execution by itself.

## Recovery and dedupe

Recovery uses the lineage, authority hash, source fingerprint, and idempotency key so a
restart can identify the same logical action without reconstructing authority from stale
worker state. A changed live lease produces a changed authority hash/context identity.

## Denial handling

Denial is diagnostic input, not an authority source.

- `SECURITY_STOP`: terminal, no automatic retry.
- authority/policy/scope/credential/private-network denials: no automatic retry; an
  external owner/policy change is required.
- network/transient failures: at most one retry with the exact same authority context.

A denial cannot change host, protocol, method, identity, credential scope, capability,
or owner authority root.

## Credential rule

The coordination ledger stores credential references/scopes only. It never stores or
materializes raw credential values. Runtime secret possession remains owned by the
credential broker/possession loop.

## Production integration

The hourly Shared Discovery Authority Cycle now builds the coordination ledger after the
live discovery capability leases are refreshed. The ledger is preserved in the existing
`shared-discovery-authority-state` artifact alongside discovery, lease, and probe state.

This gives META/X/SENJU/child workers one shared lineage and handoff format while keeping
the effective authority equal to or narrower than the live lease that entered the cycle.
