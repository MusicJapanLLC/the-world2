# Jules Fix Loop Contract

This document specifies the contract and procedure for using Jules issue-driven fix loops when OpenHands reports a `BLOCK` audit verdict on a Pull Request.

---

## 1. Overview & Roles

- **OpenHands (`openhands-ai[bot]`)**: Independent reviewer agent that performs merge-readiness audits on PR head SHAs and outputs machine-readable verdicts (`AI_MERGE_AUDIT: PASS <sha>` or `AI_MERGE_AUDIT: BLOCK <sha>`).
- **Jules (`[Jules]` Issue Router)**: Implementation and fix agent that automatically listens for issues titled `[Jules] ...`, launches an autonomous resolution session in `AUTO_CREATE_PR` mode, and submits targeted PRs with fixes.
- **Auto-Merge Governance**: Prevents unreviewed PRs or PRs with active/unresolved `BLOCK` verdicts from merging.

---

## 2. Triggering Jules on OpenHands BLOCK

When OpenHands posts a comment containing `AI_MERGE_AUDIT: BLOCK <head_sha>`:

1. **Create a `[Jules]` Issue**:
   - Issue Title format: `[Jules] Fix OpenHands audit BLOCK on PR #<PR_NUMBER>` (or any title starting with `[Jules]`).
   - Issue Body should contain:
     - The target PR number and head SHA (`<head_sha>`).
     - The specific code review / audit failure details reported by OpenHands.
     - Link to the original PR or issue.

2. **Automated Dispatch (`jules-issue-router.yml`)**:
   - The `.github/workflows/jules-issue-router.yml` workflow automatically triggers on issue creation.
   - It validates `JULES_API_KEY` and creates a Jules session with `automationMode: "AUTO_CREATE_PR"`.
   - Jules executes the required fixes, runs tests, and opens a new PR (or pushes updates to the fix branch).

3. **Re-Audit and Merge Loop**:
   - When the fix PR is opened / updated, `.github/workflows/openhands-audit-router.yml` triggers automatically for the new head SHA, summoning `@openhands` for a fresh independent audit.
   - Once OpenHands verifies the fix and posts `AI_MERGE_AUDIT: PASS <new_head_sha>`, the hardened `auto-merge.yml` workflow merges the PR into the default branch once CI checks pass.

---

## 3. Machine Verdict Specification

- `AI_MERGE_AUDIT: PASS <head_sha>`
- `AI_MERGE_AUDIT: BLOCK <head_sha>`

An existing `BLOCK` verdict on an older SHA does not block a newer head SHA once a matching `PASS` is issued for the newer head SHA.
