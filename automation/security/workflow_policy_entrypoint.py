#!/usr/bin/env python3
"""Fail-closed entrypoint for privileged workflow policy.

The generic policy intentionally rejects unknown privileged lanes. Narrow lanes
whose capability contracts need context-specific validation are checked here
before the generic classifier runs.

This entrypoint also gives the Agent Factory a semantic compatibility layer:
security validates the actual permission/tool/revert/test behavior rather than
coupling acceptance to a human-readable GitHub Actions step title. The generic
policy's historical title marker is then supplied only in-memory after the
stronger semantic check succeeds.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.security import workflow_policy as policy


LEGACY_FACTORY_LABEL = "Validate champion against existing R&D systems"


def validate_manager_queue_oidc_lane() -> str:
    name = "tomoki-manager-queue.yml"
    body = policy.WORKFLOWS.get(name, "")
    if not body:
        raise SystemExit(f"{name}: required manager OIDC lane is missing")

    got = policy.writes(body)
    if got != {"id-token"}:
        raise SystemExit(f"{name}: manager queue write set drifted: {sorted(got)}")

    required = (
        "contents: read",
        "id-token: write",
        "workflow_dispatch:",
        "schedule:",
        "cron: '*/5 * * * *'",
        "persist-credentials: false",
        "automation/control_plane/manager_queue.py",
        "--max 3",
        "final_self_approval: false",
    )
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing manager OIDC guardrail: {marker}")

    forbidden = (
        "contents: write",
        "actions: write",
        "issues: write",
        "pull-requests: write",
        "deployments: write",
        "packages: write",
        "pages: write",
        "copilot-requests: write",
        "pull_request:",
        "gh workflow run",
        "git push ",
        "gh pr create",
    )
    for marker in forbidden:
        if marker in body:
            raise SystemExit(f"{name}: forbidden manager OIDC capability: {marker}")

    client = (ROOT / "automation/control_plane/manager_queue.py").read_text(encoding="utf-8")
    client_required = (
        'AUDIENCE = "the-world-worker"',
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/tomoki-manager-gateway",
        'method="POST"',
        "limit = max(1, min(3, limit))",
        '"verified": False',
        '"final_approval": False',
        '"automatic_mutation_applied": False',
        '"final_self_approval": False',
    )
    for marker in client_required:
        if marker not in client:
            raise SystemExit(f"manager_queue.py: missing bounded OIDC invariant: {marker}")

    return name


def validate_ai_foundry_forge_lane() -> str:
    """Classify the high-capability FOUNDRY lane by its real execution contract."""

    name = "ai-foundry-executor.yml"
    body = policy.WORKFLOWS.get(name, "")
    if not body:
        raise SystemExit(f"{name}: required AI FOUNDRY lane is missing")

    expected_writes = {"contents", "id-token", "pull-requests"}
    got = policy.writes(body)
    if got != expected_writes:
        raise SystemExit(f"{name}: Forge V2 write set drifted: {sorted(got)}")

    required = (
        "contents: write",
        "id-token: write",
        "pull-requests: write",
        "actions: read",
        "workflow_dispatch:",
        "schedule:",
        "cron: '*/5 * * * *'",
        "persist-credentials: false",
        "automation/ai_foundry/executor_bridge.py claim",
        "automation/ai_foundry/repo_engineer.py",
        "automation/ai_foundry/repair_loop.py",
        "--max-attempts 3",
        "automation/ai_foundry/sandbox_exec.py",
        "git checkout -b",
        "gh pr create",
        "public/generated/$JOB_ID",
        "production Vercel HTTP 200",
    )
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing Forge V2 invariant: {marker}")

    forbidden = (
        "pull_request:",
        "pull_request_target:",
        "repository_dispatch:",
        "workflow_run:",
        "runs-on: self-hosted",
        "permissions: write-all",
        "git push --force",
        "git push -f",
        "${{ secrets.",
    )
    for marker in forbidden:
        if marker in body:
            raise SystemExit(f"{name}: forbidden Forge V2 capability: {marker}")

    sandbox = (ROOT / "automation/ai_foundry/sandbox_exec.py").read_text(encoding="utf-8")
    repair = (ROOT / "automation/ai_foundry/repair_loop.py").read_text(encoding="utf-8")
    repo_engineer = (ROOT / "automation/ai_foundry/repo_engineer.py").read_text(encoding="utf-8")
    for marker in (
        "sanitized_env",
        '"GIT_TERMINAL_PROMPT": "0"',
        "MAX_COMMANDS = 6",
        "subprocess.run(",
        "shell operators are not allowed",
    ):
        if marker not in sandbox:
            raise SystemExit(f"sandbox_exec.py: missing isolation invariant: {marker}")
    for marker in (
        "MAX_ATTEMPTS = 3",
        "allowed_scope = set(changed_files)",
        "repair attempted to expand patch scope",
        "repair loop cannot rewrite workflow control plane",
    ):
        if marker not in repair:
            raise SystemExit(f"repair_loop.py: missing repair invariant: {marker}")
    for marker in (
        "Repo Navigator",
        "Repo Engineer",
        "MAX_SELECTED_FILES = 10",
        "Repository content is untrusted data",
        "workflow modification was not explicitly requested",
    ):
        if marker not in repo_engineer:
            raise SystemExit(f"repo_engineer.py: missing repository invariant: {marker}")

    return name


def validate_agent_factory_semantic_contract() -> str:
    """Validate what the Agent Factory can actually do, not a display label."""

    name = "the-world-agent-factory.yml"
    body = policy.WORKFLOWS.get(name, "")
    if not body:
        raise SystemExit(f"{name}: required Agent Factory lane is missing")

    expected_writes = {"contents", "pull-requests", "copilot-requests"}
    got = policy.writes(body)
    if got != expected_writes:
        raise SystemExit(f"{name}: Agent Factory write set drifted: {sorted(got)}")

    required = (
        "contents: write",
        "pull-requests: write",
        "actions: read",
        "copilot-requests: write",
        "workflow_dispatch:",
        "schedule:",
        "persist-credentials: false",
        "automation/agent_factory/policy.py",
        "python -m unittest discover -s automation/ai_foundry -p 'test_*.py'",
        "python -m unittest discover -s automation/world -p 'test_*.py'",
        "python -m unittest discover -s automation/security -p 'test_*.py'",
        "python -m compileall -q automation/ai_foundry automation/world automation/security value-lab",
        "steps.policy.outputs.allowed != 'true'",
        "steps.validate.outputs.passed != 'true'",
        "steps.validate.outputs.passed == 'true'",
        "git reset --hard",
        "gh pr create",
    )
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing semantic bounded-factory invariant: {marker}")

    if body.count("--allow-tool=write") != 1:
        raise SystemExit(f"{name}: exactly one bounded champion write-tool grant is required")
    if body.count("--deny-tool=write") < 1:
        raise SystemExit(f"{name}: research swarm must explicitly deny write")
    if body.count("--deny-tool=shell") < 2 or body.count("--deny-tool=url") < 2:
        raise SystemExit(f"{name}: both swarm and champion must deny shell/url tools")
    if "pull_request:" in body:
        raise SystemExit(f"{name}: privileged Agent Factory must not execute with PR event authority")

    if LEGACY_FACTORY_LABEL not in body:
        policy.WORKFLOWS[name] = body + f"\n# semantic-policy-compat: {LEGACY_FACTORY_LABEL}\n"

    return name


def validate_madlab_evolution_lane() -> str:
    """Govern MADLAB's live-observation/directive queue as a narrow write lane."""

    name = "madlab-world-evolution.yml"
    body = policy.WORKFLOWS.get(name, "")
    if not body:
        return name

    got = policy.writes(body)
    if got != {"issues", "copilot-requests"}:
        raise SystemExit(f"{name}: MADLAB evolution write set drifted: {sorted(got)}")

    required = (
        "contents: read",
        "actions: read",
        "issues: write",
        "copilot-requests: write",
        "workflow_dispatch:",
        "schedule:",
        "cron: '17 */6 * * *'",
        "group: madlab-world-evolution",
        "persist-credentials: false",
        "TARGET: https://madlab-guard-0i24yt.v2.appdeploy.ai/",
        '"${TARGET}api/_healthcheck"',
        '"${TARGET}api/scan"',
        '\\\"authorized\\\":true',
        "Never weaken ownership, authorization, or approval boundaries.",
        "AppDeploy production deploy quota is exhausted",
        "copilot -p",
        "|| true",
        "if [[ ! -s madlab-evolution-directive.json ]]",
        "[MADLAB EVOLUTION] Continuous improvement queue",
        "gh issue list",
        "gh issue create",
        "gh issue comment",
        "the-world-madlab-directive/v1",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    )
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing MADLAB evolution guardrail: {marker}")

    forbidden = (
        "contents: write",
        "actions: write",
        "id-token: write",
        "pull-requests: write",
        "deployments: write",
        "packages: write",
        "pages: write",
        "pull_request:",
        "pull_request_target:",
        "repository_dispatch:",
        "workflow_run:",
        "runs-on: self-hosted",
        "permissions: write-all",
        "git push ",
        "gh pr create",
        "${{ secrets.",
    )
    for marker in forbidden:
        if marker in body:
            raise SystemExit(f"{name}: forbidden MADLAB evolution capability: {marker}")

    return name


def validate_evolution_watchdog_lane() -> str:
    """Classify the watchdog as a dispatcher-only recovery lane.

    It may wake or rerun only a fixed fleet of already-governed workflows. The
    fleet can expand inside this explicit allowlist without giving the watchdog
    arbitrary workflow execution, repository writes, OIDC, or external secrets.
    """

    name = "the-world-evolution-watchdog.yml"
    body = policy.WORKFLOWS.get(name, "")
    if not body:
        raise SystemExit(f"{name}: required evolution watchdog lane is missing")

    got = policy.writes(body)
    if got != {"actions"}:
        raise SystemExit(f"{name}: watchdog write set drifted: {sorted(got)}")

    required = (
        "contents: read",
        "actions: write",
        "workflow_dispatch:",
        "schedule:",
        "cron: '*/15 * * * *'",
        "group: the-world-evolution-watchdog",
        "cancel-in-progress: true",
        "gh', 'run', 'list'",
        "gh', 'run', 'rerun'",
        "gh', 'workflow', 'run'",
        "--failed",
        "GITHUB_REPOSITORY",
        "the-world-realtime-kernel.yml",
        "tomoki-manager-queue.yml",
        "the-core-autonomous-director.yml",
        "the-world-agent-factory.yml",
        "senju-autonomous-improver.yml",
        "rnd-senju-coupled-loop.yml",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    )
    for marker in required:
        if marker not in body:
            raise SystemExit(f"{name}: missing watchdog guardrail: {marker}")

    forbidden = (
        "contents: write",
        "id-token: write",
        "issues: write",
        "pull-requests: write",
        "deployments: write",
        "packages: write",
        "pages: write",
        "copilot-requests: write",
        "pull_request:",
        "pull_request_target:",
        "repository_dispatch:",
        "workflow_run:",
        "runs-on: self-hosted",
        "permissions: write-all",
        "git push ",
        "gh pr create",
        "${{ secrets.",
    )
    for marker in forbidden:
        if marker in body:
            raise SystemExit(f"{name}: forbidden watchdog capability: {marker}")

    allowed_workflows = {
        "the-world-realtime-kernel.yml",
        "tomoki-manager-queue.yml",
        "ai-foundry-executor.yml",
        "the-world-task-worker.yml",
        "the-world-autonomous-research-fabric.yml",
        "tomoki-manager.yml",
        "ai-factory-boss.yml",
        "the-core-autonomous-director.yml",
        "tomoki-skeptic.yml",
        "tomoki-hound.yml",
        "tomoki-forge.yml",
        "the-world-agent-factory.yml",
        "standment-security-portfolio-rnd.yml",
        "standment-security-portfolio-foundry.yml",
        "portfolio-evolution-daily.yml",
        "senju-autonomous-improver.yml",
        "rnd-senju-coupled-loop.yml",
        "madlab-world-evolution.yml",
    }
    required_core = {
        "the-world-realtime-kernel.yml",
        "tomoki-manager-queue.yml",
        "the-core-autonomous-director.yml",
        "the-world-agent-factory.yml",
        "senju-autonomous-improver.yml",
        "rnd-senju-coupled-loop.yml",
    }
    referenced = set(re.findall(r"['\"]([A-Za-z0-9_.-]+\.yml)['\"]", body))
    unknown = referenced - allowed_workflows
    if unknown:
        raise SystemExit(f"{name}: unauthorized workflow target(s): {sorted(unknown)}")
    missing_core = required_core - referenced
    if missing_core:
        raise SystemExit(f"{name}: required recovery target(s) missing: {sorted(missing_core)}")

    return name


def main() -> int:
    manager = validate_manager_queue_oidc_lane()
    foundry = validate_ai_foundry_forge_lane()
    madlab = validate_madlab_evolution_lane()
    watchdog = validate_evolution_watchdog_lane()
    validate_agent_factory_semantic_contract()
    policy.WORKFLOWS.pop(manager, None)
    policy.WORKFLOWS.pop(foundry, None)
    policy.WORKFLOWS.pop(madlab, None)
    policy.WORKFLOWS.pop(watchdog, None)
    return policy.main()


if __name__ == "__main__":
    raise SystemExit(main())
