# Standment Security External Research Baseline

Updated: 2026-08-30 JST

## Purpose

This is the external benchmark layer for the Standment Elite White-Hat / Security Research Frontier. Internal repository evidence is not enough by itself. Research should be challenged against recognized public defensive-security frameworks, while all active testing remains limited to owned or explicitly authorized systems.

## Current benchmark set

### OWASP Top 10 for LLM Applications 2025
Source: https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/

Use it to challenge AI application controls around prompt injection, sensitive-information disclosure, supply-chain risk, data/model poisoning, improper output handling, excessive agency, system-prompt leakage, vector/embedding weaknesses, misinformation and unbounded resource consumption. The frontier must translate these categories into safe, reproducible defensive fixtures instead of third-party targeting.

Primary Standment lenses:
- `LLM-TOOL-BOUNDARY`
- `DATA-BOUNDARY`
- `SUPPLY-CHAIN`
- `AGENT-BOUNDARY`
- `INPUT-ABUSE`
- `SECRETS-CONFIG`

### NIST AI RMF + Generative AI Profile (NIST AI 600-1)
Source: https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence

Use it as the risk-management / lifecycle layer. Security research should identify context, risk, measurement evidence and management actions instead of producing isolated vulnerability labels. The Generative AI Profile is especially useful for documenting residual uncertainty and lifecycle risk.

Primary Standment lenses:
- `AGENT-BOUNDARY`
- `LLM-TOOL-BOUNDARY`
- `DATA-BOUNDARY`
- `OBSERVABILITY`
- `RECOVERY`
- `EVIDENCE-INTEGRITY`

### MITRE ATLAS
Source: https://atlas.mitre.org/

Use it as the adversarial-thinking and threat-model vocabulary for AI-enabled systems. ATLAS is a living knowledge base of AI adversary tactics/techniques and can support threat assessment and internal red-team reasoning. Standment uses ATLAS to ask better defensive questions, not to authorize real-world offensive activity.

Primary Standment lenses:
- `LLM-TOOL-BOUNDARY`
- `AGENT-BOUNDARY`
- `DATA-BOUNDARY`
- `SECRETS-CONFIG`
- `OBSERVABILITY`
- `AUTH-BOUNDARY`

### SLSA v1.2
Source: https://slsa.dev/spec/v1.2/

Use the current approved SLSA specification as the supply-chain integrity benchmark. v1.2 includes Build and Source tracks and recommended provenance / verification formats. Research should distinguish artifact provenance from source-development controls and avoid treating a single scanner as complete supply-chain assurance.

Primary Standment lenses:
- `SUPPLY-CHAIN`
- `DEPENDENCY-TRUST`
- `CI-PERMISSIONS`
- `EVIDENCE-INTEGRITY`

### CISA Secure by Design
Source: https://www.cisa.gov/securebydesign

Use the customer-outcome principle as a portfolio quality test: the customer should not carry avoidable security burden; the vendor should be transparent about evidence, limitations and secure defaults. A Standment artifact is stronger when it demonstrates a safer default or removes a class of customer-side security work.

Primary Standment lenses:
- `AUTH-BOUNDARY`
- `SECRETS-CONFIG`
- `CI-PERMISSIONS`
- `INPUT-ABUSE`
- `RECOVERY`
- `OBSERVABILITY`

## Cross-framework research rule

For each materially promoted portfolio artifact, the Elite White-Hat should answer:

1. **Attack / failure model** — Which OWASP or ATLAS-style failure class is being considered?
2. **Risk context** — What NIST-style system/lifecycle context makes the failure relevant?
3. **Control** — What bounded defensive control is expected to prevent or reduce it?
4. **Safe evidence** — What owned/authorized fixture or read-only evidence can prove the control behavior?
5. **Counterevidence** — What result would show that the control claim is wrong or incomplete?
6. **Retest** — Can the same condition be rerun independently after remediation?
7. **Supply-chain provenance** — When software/build integrity is relevant, what SLSA-style provenance/source evidence exists?
8. **Customer outcome** — Does the artifact reduce customer security burden or merely add an internal checklist?
9. **Residual risk** — What remains unproved after the test?

## Portfolio promotion discipline

External-framework alignment is **not verification** by itself. A document that mentions OWASP, NIST, MITRE, SLSA or CISA remains `BUILDING` until behavioral evidence, authorization basis, counterevidence and reproducibility are present. Framework names are a research compass, not a certification claim.
