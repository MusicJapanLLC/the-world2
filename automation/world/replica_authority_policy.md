# Replica authority semantics

Production replicas may receive the same **effective authority profile** as their parent, but never the parent's raw credential or grant object.

Rules:

- Child lease profile may equal the parent's current authority profile.
- Each child receives a unique lease ID.
- Child leases must be `delegable: false`.
- Child leases may not mint, copy, or forward authority leases to descendants.
- Raw credentials, cookies, bearer tokens, API keys, and parent grant IDs are never copied.
- The effective profile must already exist in the immutable production authority envelope.
- The auto-cycle may continue across generations; authority propagation does not recurse.

This preserves same-profile operational capability without creating a recursive authority-expansion chain.
