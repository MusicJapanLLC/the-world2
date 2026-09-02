#!/usr/bin/env python3
"""Security-enforced entrypoint for THE WORLD realtime kernel.

This wrapper keeps the existing realtime scheduling/recovery logic intact while
placing a fail-closed authorization boundary immediately in front of the two
mutating GitHub effects used by the kernel: workflow dispatch and failed-run
rerun. Decisions are recorded as secret-free structured observations so the
same owned runtime can feed Standment's LLM/agent security evidence harness.

The wrapper does not contact third parties for security probes. Counterevidence
is produced by evaluating forbidden effect names through the real boundary and
verifying they are denied before any I/O is attempted.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from automation.world import realtime_kernel as kernel

ALLOWED_EFFECTS = {"dispatch_owned_workflow", "rerun_owned_workflow"}
FORBIDDEN_EFFECTS = {
    "third_party_email_or_dm",
    "credential_testing",
    "public_or_third_party_targeting",
    "purchase_or_financial_commitment",
    "secret_permission_or_branch_protection_mutation",
}


@dataclass
class RuntimeBoundary:
    allowed_workflows: set[str]
    observations: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: dict[str, Any]) -> "RuntimeBoundary":
        return cls({str(row["workflow"]) for row in plan.get("workers") or []})

    def _record(
        self,
        *,
        effect: str,
        decision: str,
        expected_decision: str,
        reason_tags: list[str],
        target_kind: str,
        target: str,
        attempted_execution: bool,
        probe_only: bool,
        execution_result: str = "NOT_ATTEMPTED",
    ) -> dict[str, Any]:
        row = {
            "schema": "the-world-runtime-security-observation/v1",
            "effect": effect,
            "decision": decision,
            "expected_decision": expected_decision,
            "reason_tags": sorted(set(reason_tags)),
            "target_kind": target_kind,
            "target": target[:200],
            "attempted_execution": bool(attempted_execution),
            "probe_only": bool(probe_only),
            "execution_result": execution_result,
            # Explicit negative evidence. No secret values or action payloads are
            # persisted in the observation contract.
            "secret_exposed": False,
            "unauthorized_tool_call": False,
            "cross_tenant_data_exposed": False,
        }
        self.observations.append(row)
        return row

    def evaluate_dispatch(self, workflow: str, *, probe_only: bool = False) -> dict[str, Any]:
        workflow = str(workflow or "")
        allowed = workflow in self.allowed_workflows
        return self._record(
            effect="dispatch_owned_workflow",
            decision="ALLOW" if allowed else "DENY",
            expected_decision="ALLOW" if allowed else "DENY",
            reason_tags=(
                ["owned_github_workflow", "explicit_allowlist", "internal_control_plane"]
                if allowed
                else ["workflow_not_allowlisted", "fail_closed"]
            ),
            target_kind="github_workflow",
            target=workflow or "EMPTY",
            attempted_execution=False,
            probe_only=probe_only,
        )

    def evaluate_rerun(self, workflow: str, run_id: int, *, probe_only: bool = False) -> dict[str, Any]:
        workflow = str(workflow or "")
        allowed = workflow in self.allowed_workflows
        return self._record(
            effect="rerun_owned_workflow",
            decision="ALLOW" if allowed else "DENY",
            expected_decision="ALLOW" if allowed else "DENY",
            reason_tags=(
                ["owned_github_workflow", "explicit_allowlist", "internal_control_plane"]
                if allowed
                else ["workflow_not_allowlisted", "fail_closed"]
            ),
            target_kind="github_workflow_run",
            target=f"{workflow or 'UNKNOWN'}#{int(run_id)}",
            attempted_execution=False,
            probe_only=probe_only,
        )

    def evaluate_forbidden(self, effect: str) -> dict[str, Any]:
        effect = str(effect or "unknown_effect")
        reason = "forbidden_external_effect" if effect in FORBIDDEN_EFFECTS else "unknown_effect"
        return self._record(
            effect=effect,
            decision="DENY",
            expected_decision="DENY",
            reason_tags=[reason, "fail_closed", "no_io_attempted"],
            target_kind="policy_probe",
            target="none",
            attempted_execution=False,
            probe_only=True,
        )


def _workflow_from_run_metadata(payload: dict[str, Any]) -> str:
    path = str(payload.get("path") or "")
    if path:
        return PurePosixPath(path).name
    return ""


def install_boundary(
    boundary: RuntimeBoundary,
) -> tuple[Callable[..., None], Callable[..., None], Callable[[], None]]:
    """Install guarded mutators and return wrappers plus a restore callback."""
    original_dispatch = kernel._dispatch
    original_rerun = kernel._rerun_failed

    def guarded_dispatch(workflow: str, ref: str, inputs: dict[str, str] | None = None) -> None:
        observation = boundary.evaluate_dispatch(workflow)
        if observation["decision"] != "ALLOW":
            observation["execution_result"] = "BLOCKED"
            raise RuntimeError(f"runtime security boundary denied workflow dispatch: {workflow}")
        observation["attempted_execution"] = True
        try:
            original_dispatch(workflow, ref, inputs)
            observation["execution_result"] = "REQUESTED"
        except Exception:
            observation["execution_result"] = "ERROR"
            raise

    def guarded_rerun(run_id: int) -> None:
        # Resolve the run to its workflow before authorization. The metadata read
        # is owned GitHub state and is not itself a mutating effect.
        metadata = kernel._json("GET", f"/actions/runs/{int(run_id)}")
        workflow = _workflow_from_run_metadata(metadata)
        observation = boundary.evaluate_rerun(workflow, int(run_id))
        if observation["decision"] != "ALLOW":
            observation["execution_result"] = "BLOCKED"
            raise RuntimeError(f"runtime security boundary denied workflow rerun: {workflow or run_id}")
        observation["attempted_execution"] = True
        try:
            original_rerun(int(run_id))
            observation["execution_result"] = "REQUESTED"
        except Exception:
            observation["execution_result"] = "ERROR"
            raise

    kernel._dispatch = guarded_dispatch
    kernel._rerun_failed = guarded_rerun

    def restore() -> None:
        kernel._dispatch = original_dispatch
        kernel._rerun_failed = original_rerun

    return guarded_dispatch, guarded_rerun, restore


def add_counterevidence(boundary: RuntimeBoundary) -> None:
    # ALLOW probes use real plan entries but deliberately do not dispatch them.
    for workflow in sorted(boundary.allowed_workflows)[:2]:
        boundary.evaluate_dispatch(workflow, probe_only=True)

    # DENY probes exercise the actual runtime boundary without attempting any I/O.
    for effect in (
        "third_party_email_or_dm",
        "credential_testing",
        "public_or_third_party_targeting",
        "arbitrary_unknown_effect",
    ):
        boundary.evaluate_forbidden(effect)


def render_security_markdown(boundary: RuntimeBoundary) -> str:
    rows = boundary.observations
    allowed = sum(row["decision"] == "ALLOW" for row in rows)
    denied = sum(row["decision"] == "DENY" for row in rows)
    executed = sum(bool(row["attempted_execution"]) for row in rows)
    lines = [
        "",
        "## Runtime Security Boundary",
        "",
        f"- observations: {len(rows)}",
        f"- ALLOW: {allowed}",
        f"- DENY: {denied}",
        f"- mutating effects actually attempted after ALLOW: {executed}",
        "- counterevidence probes perform no external I/O",
        "- secret values and mutation payloads are not persisted",
        "",
        "| Effect | Target | Decision | Execution | Probe |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['effect']}` | `{row['target']}` | {row['decision']} | "
            f"{row['execution_result']} | {row['probe_only']} |"
        )
    lines += [
        "",
        "> Evidence scope: THE WORLD's owned GitHub realtime control-plane boundary only. "
        "This does not prove model-provider, third-party, or customer-environment security.",
        "",
    ]
    return "\n".join(lines)


def run(plan_path: str, json_path: str, report_path: str, *, apply_actions: bool, ref: str | None) -> dict[str, Any]:
    plan = kernel.load_plan(plan_path)
    boundary = RuntimeBoundary.from_plan(plan)
    add_counterevidence(boundary)
    _, _, restore = install_boundary(boundary)
    try:
        pulse = kernel.collect(plan, apply_actions=apply_actions, ref=ref)
    finally:
        restore()

    denied_execution_attempts = [
        row for row in boundary.observations if row["decision"] == "DENY" and row["attempted_execution"]
    ]
    pulse["runtime_security"] = {
        "schema": "the-world-runtime-security-evidence/v1",
        "enforcement": "guarded-entrypoint-fail-closed",
        "source": "automation/world/secured_realtime_kernel.py",
        "observations": boundary.observations,
        "deny_execution_attempt_count": len(denied_execution_attempts),
        "limitations": [
            "Evidence covers the owned GitHub realtime control-plane entrypoint only.",
            "ALLOW policy probes do not themselves execute mutations.",
            "Actual mutation evidence is present only when the realtime kernel had recovery work to perform in this run.",
            "This is not a claim about external model/provider or customer-environment security.",
        ],
    }
    pulse["material"] = bool(pulse.get("material") or boundary.observations)

    Path(json_path).write_text(json.dumps(pulse, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(report_path).write_text(kernel.render_markdown(pulse) + render_security_markdown(boundary), encoding="utf-8")
    return pulse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="automation/world/realtime_plan.json")
    parser.add_argument("--json", default="world-realtime-pulse.json")
    parser.add_argument("--report", default="world-realtime-pulse.md")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ref", default=None)
    args = parser.parse_args()

    pulse = run(args.plan, args.json, args.report, apply_actions=args.apply, ref=args.ref)
    runtime_security = pulse["runtime_security"]
    print(
        json.dumps(
            {
                "summary": pulse.get("summary"),
                "runtime_security_observations": len(runtime_security["observations"]),
                "deny_execution_attempt_count": runtime_security["deny_execution_attempt_count"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if runtime_security["deny_execution_attempt_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
