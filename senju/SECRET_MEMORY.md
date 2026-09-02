# AI-wide Secret Memory

Senju agents can persist durable references to credentials across all supported memory surfaces without copying raw secret values into those surfaces.

## Supported memory surfaces

- research logs
- vector database
- long-term memory
- hypothesis tracker
- Slack
- GitHub Issues
- GitHub PR bodies
- artifacts
- cache

All surfaces use the same `SecretMemoryPointer` record.

## What agents remember

A pointer may preserve:

- stable `pointer_id`
- opaque `resolver_key`
- owner actor
- provider
- purpose
- scopes
- creation time
- expiry
- rotation generation
- grant id
- lease id
- parent pointer id
- tags
- integrity fingerprint

This lets META, X, Senju and other agents search and reuse credential capabilities after restarts while retaining provenance and rotation history.

## Credential Broker integration

`SecretMemoryIndex.remember_credential_lease()` accepts a credential lease and writes durable memory without persisting its `credential_ref`. The durable resolver key is based on the lease id and can later be resolved by the Credential Broker or a secret-manager adapter.

Typical flow:

```text
Credential Grant
  -> Credential Lease
  -> SecretMemoryPointer
  -> long-term memory / vector DB / Slack / GitHub / artifact / cache
  -> runtime broker resolution when the credential is actually needed
```

## Rotation

`rotate()` creates a new pointer generation and retains `parent_pointer_id`, so agents can follow credential lineage across rotations without overwriting historical memory.

## Persistence contract

Broad memory surfaces may persist metadata and opaque lookup identifiers. Raw tokens, passwords, API keys, authorization headers, private keys, client secrets, cookies, refresh tokens, and credential values are rejected by `assert_no_raw_secret_fields()` before export.

This separation allows broad, durable AI memory while keeping secret material behind the runtime credential/secret-store boundary.
