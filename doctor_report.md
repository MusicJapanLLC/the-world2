# 🩺 Development Environment & Repository Health Audit Report

## 1. Workflow YAML & Script Reference Audit
- **Workflows Checked**: 71
- **Parse Errors**: None (All workflows parseable)
- **Missing Script References**:
  - ❌ tomoki-forge.yml references missing script 'tmp/tomoki-verify.sh'
  - ❌ tomoki-forge.yml references missing script 'tmp/world-self-heal-engine.py'
  - ❌ tomoki-forge.yml references missing script 'tmp/tomoki-policy-gate.py'
  - ❌ tomoki-forge.yml references missing script 'tmp/world-self-heal-merge.py'
  - ❌ tomoki-forge.yml references missing script 'tmp/world-self-heal-policy.py'
  - ❌ tomoki-forge.yml references missing script 'tmp/tomoki-slack-post.py'
  - ❌ tomoki-forge.yml references missing script 'tmp/world-self-heal-verify.sh'
- **Frequent / Duplicated Triggers**:
  - ℹ️ Trigger 'schedule:' shared by 31 workflows: ai-factory-boss.yml, ai-security-handoff-consumer.yml, gmail-service-health.yml, senju-daily-report.yml, senju-external-contact.yml
  - ℹ️ Trigger 'push:' shared by 11 workflows: deploy-iyomaru-ramen.yml, standment-security-gate.yml, codeql.yml, dependency-audit.yml, security-guard.yml
  - ℹ️ Trigger 'pull_request:' shared by 5 workflows: the-world-external-write-ci.yml, dependency-review.yml, standment-site-audit.yml, auto-merge.yml, openhands-audit-router.yml
  - ℹ️ Trigger 'workflow_dispatch:' shared by 23 workflows: senju-live-network-canary.yml, madlab-world-evolution.yml, child-private-workstation.yml, tomoki-hound.yml, ai-foundry-engineering-loop-v2.yml

## 2. Package Manifests & Lockfiles
- **Manifests Found**: package.json, requirements.txt
- **Lockfiles Found**: None
  - ⚠️ package.json present but no lockfile (package-lock.json) found.

## 3. Discoverable Test / Lint Commands
- pytest (Python test suite)

## 4. GitHub PR & CI Health
- *GitHub API token not available; skipped remote PR/CI inspection.*

---
*Audit generated automatically by `scripts/dev_doctor.py`.*