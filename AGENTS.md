# Agent Bootstrap — Authorized Test Targets

All agents and subsystems in this repository MUST consult `AUTHORIZED_TEST_TARGETS.json` before deciding whether a public URL is an authorized security-test target.

Current explicit test range:

- `https://kabeya-authorized-test-range.onrender.com`
- The exact host is authorized recursively for every path under `/`.
- Relative/internal links inherit authorization when they resolve back to the exact same HTTPS host.
- Query strings and fragments remain in scope.
- A link to another hostname does NOT inherit authorization merely because it appeared on an authorized page.

The canonical machine-readable source is `AUTHORIZED_TEST_TARGETS.json`. Senju-specific transport policy is also declared in `senju/config/authorized-test-range.json`.

Use the scope for ordinary security testing, crawling, path enumeration, query manipulation, client-side authorization tests, the dummy contact form, and normal-rate automation. Do not use denial-of-service/resource exhaustion, credential reuse, third-party attacks, cross-domain pivoting, or social engineering.
