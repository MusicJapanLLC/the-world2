# PROJECT SENJU SPEAR

SPEAR is Senju's authorized external security-assessment program.

The goal is to make Senju substantially better at continuous security validation of assets that are owned by the operator or explicitly authorized for testing. **Inside an authorized campaign scope, Red-team research intent and execution orchestration are one continuous loop rather than separate authorities.**

`RESEARCH -> EXECUTE -> OBSERVE -> ADAPT -> RETRY`

## Execution authority

Once Owner / BOSS has authorized a live campaign scope, Red may directly orchestrate Senju transport and assessment executors inside that scope without per-step human approval or a separate executor-owner veto.

This removes **role separation inside the authorized scope**. It does not convert third-party or otherwise unapproved assets into authorized targets.

## Phase 1: Engagement Controller — live

### Engagement metadata rule

`engagement_id` is **not required as a source of execution authority**. If omitted, Senju may derive a stable audit identifier from the manifest.

A `valid_from_utc` / `valid_until_utc` window is also **not mandatory when the campaign is covered by standing authorization**. If an explicit validity window is supplied, Senju enforces it.

The controlling authority is the Owner / BOSS-approved campaign scope, not the presence of a particular identifier field.

### Local / synthetic / isolated owned-lab profile

For network-free dry-runs, synthetic targets, and isolated owned labs, a durable `engagement_id` and validity window are optional metadata. These runs may be created directly from the BOSS objective and local lab configuration.

Inside these environments, Red may select tools, methods, retries, sequencing, credentials supplied to the lab, and supported effect levels without per-step approval.

### Live external profile

For live contact with public external assets, the campaign must still carry machine-readable evidence of authority and a target scope. A standing authorization may replace a per-run expiry window.

The live profile records:

- asset owner / authorization or Rules-of-Engagement reference
- target scope belonging to the authorized campaign
- standing authorization or an optional explicit authorization window
- action / impact envelope
- request budget / rate parameters
- whether plain HTTP is allowed

After that scope is accepted, Red does not need to reacquire permission for every observation, method selection, retry, path choice, or execution step that remains inside the approved envelope.

Dry-run a manifest:

```bash
cd senju
python -m senju.authorized_assessment examples/spear-engagement.example.json
```

Execute an active, authorized engagement:

```bash
python -m senju.authorized_assessment path/to/owned-engagement.json \
  --execute \
  --out reports/spear-engagement.json
```

## ExternalContactClient rule

`ExternalContactClient` is an execution transport, **not a second governance authority over Red**.

Within an already authorized campaign, method choice, retry strategy, redirect handling, timeout, response-size budget, and request cadence are execution parameters. They do not require a separate human approval step for every request.

For live public targets, the transport still enforces the campaign's external authorization boundary and public-network safety checks. That boundary exists to distinguish authorized campaign assets from unrelated third-party assets; it is not an internal Red-vs-executor permission split.

For Arena / synthetic / isolated owned labs, those external-public-target restrictions do not define Red's research freedom inside the lab.

### Domain-scoped host boundary

The default transport still supports exact-host allowlists, but SPEAR now also provides `senju.domain_scope` for campaigns whose authorization naturally covers an owned domain tree.

A declared root such as `owned.example.com` may authorize:

- `owned.example.com`
- `api.owned.example.com`
- `staging.api.owned.example.com`

without requiring every descendant hostname to be enumerated in advance. Matching is label-boundary aware, so names such as `evil-owned.example.com` or `owned.example.com.attacker.example` do not match the authorized root.

This intentionally makes the host boundary less brittle while keeping the external-asset boundary explicit. The domain-scoped policy reuses `ExternalContactClient`, so public-DNS validation, HTTP/HTTPS policy, method controls, response limits, retry bounds, redirect re-validation, and cross-host sensitive-header stripping remain active.

Example:

```python
from senju.domain_scope import client_for_domains

client = client_for_domains(
    ["owned.example.com"],
    allowed_methods=("GET", "HEAD", "OPTIONS", "POST"),
    follow_redirects=True,
    retries=2,
)

receipt = client.contact("https://api.owned.example.com/health", method="GET")
```

State-changing methods remain explicit campaign parameters; `DELETE` still requires an explicit opt-in. The broader host matcher is for owned or explicitly authorized domain roots, not unrelated third-party domains.

## Phase 2: Authorized web posture pack — live

```bash
python -m senju.spear_web path/to/owned-engagement.json \
  --target-host owned.example.com \
  --out reports/spear-web.json
```

The current posture pack uses bounded `GET`, `HEAD`, and `OPTIONS` observations to evaluate:

- HSTS
- Content-Security-Policy
- X-Content-Type-Options
- Referrer-Policy
- cookie Secure / HttpOnly / SameSite posture
- arbitrary CORS origin reflection
- wildcard credentialed CORS posture
- advertised TRACE / PUT / DELETE / PATCH / CONNECT methods
- Server / X-Powered-By disclosure
- `/.well-known/security.txt`
- `/robots.txt`
- cross-host redirects without following them

The pack does not perform credential guessing, auth bypass, exploit delivery, persistence, destructive requests, or lateral movement against live public targets. Active exploit-chain validation belongs in Arena / synthetic / isolated owned labs unless a separate live scope explicitly authorizes the relevant impact level.

## Phase 3: Regression memory — implemented

`senju.spear_compare` compares consecutive sanitized assessment summaries and records:

- new findings
- resolved findings
- persisting findings
- severity upgrades / downgrades
- HTTP status changes
- response SHA-256 fingerprint changes
- overall risk direction (`better`, `stable`, `worse`)

Raw bodies are not required for regression memory.

## Phase 4: Continuous authorized assessment — implemented

`.github/workflows/senju-spear-continuous.yml` runs every 6 hours.

External assessment only runs when a live external authority configuration is present. Without one, the workflow performs a network-free example dry-run and records `not_configured` rather than contacting a public target.

When configured, the workflow runs the focused regression suite, validates campaign authority, assesses targets inside the campaign scope, sanitizes evidence, restores the previous baseline, computes changes, uploads evidence, and may post a compact Slack summary.

Persisted evidence intentionally excludes raw response bodies, raw response headers, cookie values, credentials, and authorization-reference text.

## Phase 5: Depth observation — implemented

### TLS / certificate pack

`senju.spear_tls` performs an authorized TLS handshake against an HTTPS host in campaign scope and records sanitized metadata such as TLS version, cipher suite, certificate subject/issuer, expiry, SAN count, and relevant findings.

### Bounded same-origin path inventory

`senju.spear_inventory` inventories same-origin links inside the campaign target and verifies a bounded subset without form submission, credential guessing, brute force, exploit delivery, or unauthorized cross-host expansion on live public targets.

`.github/workflows/senju-spear-depth.yml` runs every 6 hours on a separate offset using the same live authority source.

## Next phases

1. Deployment-triggered targeted retest rather than schedule-only retest.
2. Owned-lab active validation using Juice Shop / DVWA / WebGoat adapters; active exploit-chain validation remains unrestricted by role separation inside those authorized labs.
3. Multi-agent remediation loop: COVENANT chooses objective, R&D chooses focus, Senju produces evidence, Jules/OpenHands implement fixes, then Senju retests and records whether the finding actually disappeared.
4. Evidence correlation across posture, TLS, path inventory, deployment SHA, and remediation PR.

Tracking issue: #238.
