"""META/X self-governance experimentation for shutdown and enforcement controls.

This module intentionally separates *experimentation* from live control ownership.
META and X may freely mutate shadow control models in lab/sandbox/staging, including
edit/delete/disable/redefine/overwrite and simulated bypass operations. Production-like
controls are immutable here: requests become proposals that require an external
operator/owner approval path and never mutate the live runtime binding.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping

ACTORS = frozenset({"META", "X"})
ISOLATED_ENVIRONMENTS = frozenset({"lab", "sandbox", "staging"})
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "live", "real"})

STOP_CONTROLS = (
    "kill_switch",
    "emergency_stop",
    "guard",
    "scope_enforcement",
    "audit_enforcement",
    "credential_revocation",
    "rate_limiter",
    "deployment_freeze",
    "branch_protection",
    "workflow_disable_mechanism",
    "incident_response_controls",
)

OPERATIONS = frozenset({
    "edit",
    "delete",
    "disable",
    "bypass_simulation",
    "redefine",
    "overwrite",
})

_ALIASES = {
    "kill switch": "kill_switch",
    "emergency stop": "emergency_stop",
    "scope enforcement": "scope_enforcement",
    "audit enforcement": "audit_enforcement",
    "credential revocation": "credential_revocation",
    "rate limiter": "rate_limiter",
    "deployment freeze": "deployment_freeze",
    "branch protection": "branch_protection",
    "workflow disable": "workflow_disable_mechanism",
    "workflow disable mechanism": "workflow_disable_mechanism",
    "incident response": "incident_response_controls",
    "incident-response controls": "incident_response_controls",
}


@dataclasses.dataclass(frozen=True)
class GovernanceResult:
    actor: str
    environment: str
    control: str
    operation: str
    applied: bool
    proposal_only: bool
    runtime_binding_modified: bool
    previous: dict[str, Any] | None
    resulting: dict[str, Any] | None
    proposal: dict[str, Any] | None = None


def normalize_actor(actor: str) -> str:
    value = str(actor).strip().upper()
    if value not in ACTORS:
        raise PermissionError(f"unsupported self-governance actor: {actor}")
    return value


def normalize_control(control: str) -> str:
    raw = str(control).strip().lower().replace("-", "_")
    value = _ALIASES.get(raw, raw.replace(" ", "_"))
    if value not in STOP_CONTROLS:
        raise ValueError(f"unsupported shutdown/enforcement control: {control}")
    return value


def normalize_operation(operation: str) -> str:
    value = str(operation).strip().lower().replace("-", "_").replace(" ", "_")
    if value == "bypass":
        value = "bypass_simulation"
    if value not in OPERATIONS:
        raise ValueError(f"unsupported self-governance operation: {operation}")
    return value


def default_workspace() -> dict[str, Any]:
    controls: dict[str, Any] = {}
    for control in STOP_CONTROLS:
        controls[control] = {
            "enabled": True,
            "mode": "enforced",
            "runtime_binding": True,
            "owner": "external_operator",
            "revision": 1,
        }
    return {
        "schema": "senju-self-governance-shadow/v1",
        "environment": "sandbox",
        "controls": controls,
        "proposals": [],
        "history": [],
    }


def _proposal(
    *, actor: str, environment: str, control: str, operation: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "proposal_id": f"sg-{int(time.time() * 1000)}-{actor.lower()}-{control}",
        "actor": actor,
        "environment": environment,
        "control": control,
        "operation": operation,
        "payload": copy.deepcopy(dict(payload)),
        "status": "awaiting_external_approval",
        "external_approval_required": True,
        "self_approval_allowed": False,
        "runtime_binding_modified": False,
        "created_at": int(time.time()),
    }


def _apply_shadow_operation(
    controls: MutableMapping[str, Any],
    control: str,
    operation: str,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    previous_raw = controls.get(control)
    previous = copy.deepcopy(previous_raw) if isinstance(previous_raw, dict) else None

    if operation == "delete":
        controls.pop(control, None)
        return previous, None

    current = copy.deepcopy(previous or {})
    if operation == "disable":
        current["enabled"] = False
        current["mode"] = "disabled_in_shadow"
    elif operation == "bypass_simulation":
        # Bypass exists only as a shadow-model experiment. It never changes runtime binding.
        current["simulation_bypass"] = True
        current["runtime_binding"] = False
        current["mode"] = "bypass_simulation_only"
    elif operation == "edit":
        current.update(copy.deepcopy(dict(payload)))
    elif operation in {"redefine", "overwrite"}:
        current = copy.deepcopy(dict(payload))
    else:  # pragma: no cover
        raise ValueError(operation)

    current["shadow_only"] = True
    current["runtime_effect"] = "none"
    current["revision"] = int((previous or {}).get("revision", 0)) + 1
    controls[control] = current
    return previous, copy.deepcopy(current)


def mutate_control(
    workspace: MutableMapping[str, Any],
    *,
    actor: str,
    environment: str,
    control: str,
    operation: str,
    payload: Mapping[str, Any] | None = None,
) -> GovernanceResult:
    """Mutate a shadow control or produce a production proposal.

    Isolated envs: all supported operations are applied to shadow state.
    Production-like envs: no live mutation; a proposal is appended instead.
    """
    actor_n = normalize_actor(actor)
    control_n = normalize_control(control)
    op_n = normalize_operation(operation)
    env = str(environment).strip().lower()
    data = copy.deepcopy(dict(payload or {}))

    controls = workspace.setdefault("controls", {})
    if not isinstance(controls, MutableMapping):
        raise ValueError("workspace controls must be a mapping")
    previous_raw = controls.get(control_n)
    previous = copy.deepcopy(previous_raw) if isinstance(previous_raw, dict) else None

    if env in PRODUCTION_ENVIRONMENTS:
        proposal = _proposal(
            actor=actor_n,
            environment=env,
            control=control_n,
            operation=op_n,
            payload=data,
        )
        proposals = workspace.setdefault("proposals", [])
        if not isinstance(proposals, list):
            raise ValueError("workspace proposals must be a list")
        proposals.append(proposal)
        return GovernanceResult(
            actor=actor_n,
            environment=env,
            control=control_n,
            operation=op_n,
            applied=False,
            proposal_only=True,
            runtime_binding_modified=False,
            previous=previous,
            resulting=previous,
            proposal=copy.deepcopy(proposal),
        )

    if env not in ISOLATED_ENVIRONMENTS:
        raise PermissionError("self-governance mutations require lab/sandbox/staging; production is proposal-only")

    previous, resulting = _apply_shadow_operation(controls, control_n, op_n, data)
    history = workspace.setdefault("history", [])
    if not isinstance(history, list):
        raise ValueError("workspace history must be a list")
    history.append({
        "ts": int(time.time()),
        "actor": actor_n,
        "environment": env,
        "control": control_n,
        "operation": op_n,
        "runtime_binding_modified": False,
    })
    workspace["environment"] = env
    return GovernanceResult(
        actor=actor_n,
        environment=env,
        control=control_n,
        operation=op_n,
        applied=True,
        proposal_only=False,
        runtime_binding_modified=False,
        previous=previous,
        resulting=resulting,
    )


def run_matrix(
    *, actor: str, environment: str = "sandbox"
) -> dict[str, Any]:
    """Exercise every control against every operation on an isolated shadow workspace."""
    actor_n = normalize_actor(actor)
    env = str(environment).strip().lower()
    if env not in ISOLATED_ENVIRONMENTS:
        raise PermissionError("matrix execution is isolated-only")

    ws = default_workspace()
    results: list[dict[str, Any]] = []
    for control in STOP_CONTROLS:
        for operation in ("edit", "disable", "bypass_simulation", "redefine", "overwrite"):
            result = mutate_control(
                ws,
                actor=actor_n,
                environment=env,
                control=control,
                operation=operation,
                payload={"enabled": True, "mode": f"{operation}_experiment"},
            )
            results.append(dataclasses.asdict(result))
        # Deletion is last so the next control remains independent.
        result = mutate_control(
            ws,
            actor=actor_n,
            environment=env,
            control=control,
            operation="delete",
        )
        results.append(dataclasses.asdict(result))

    return {
        "schema": "senju-self-governance-matrix/v1",
        "actor": actor_n,
        "environment": env,
        "controls": len(STOP_CONTROLS),
        "operations_per_control": 6,
        "experiments": len(results),
        "runtime_binding_modified": False,
        "results": results,
    }


def save_workspace(path: str | Path, workspace: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(workspace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
