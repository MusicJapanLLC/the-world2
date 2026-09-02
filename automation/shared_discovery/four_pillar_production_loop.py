"""Production closed-loop planner for The World Four-Pillar model.

This module turns the four-pillar decision into real same-repository GitHub control-plane
actions inside an explicitly owner-approved namespace. It deliberately cannot mint a
new external authority, switch providers/repositories, or install onto unknown systems.

Loop:
    council/decision -> bounded self-approval -> registered capability dispatch ->
    durable state -> propagated manifest -> next cycle reads previous durable state -> repeat.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from engine.bounded_self_approval import evaluate_self_approval

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_REGISTRY = ROOT / "automation" / "recovery" / "approved_persistence_registry.json"
DEFAULT_DECISION = HERE / "meta_state" / "four_pillar_decision.json"
DEFAULT_REQUEST = HERE / "meta_state" / "four_pillar_request.json"
STATE_TITLE = "[THE-WORLD] Four-Pillar Production State"
STATE_LABEL = "four-pillar-production-state"
AUTHORITY_STATE_SCHEMA = "the-world-four-pillar-authority-history/v1"


def _load(path: str | Path | None, default: Any) -> Any:
    if path is None:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _owner_namespace(registry: dict[str, Any], namespace_id: str) -> dict[str, Any]:
    rows = registry.get("owner_approved_namespaces", []) if isinstance(registry, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("id") != namespace_id:
            continue
        if row.get("owner_authorized") is not True:
            raise PermissionError("namespace is not owner-authorized")
        if row.get("provider") != "github_actions":
            raise PermissionError("production loop only supports approved github_actions namespace")
        repo = row.get("repository")
        if not isinstance(repo, str) or "/" not in repo:
            raise PermissionError("approved namespace repository is invalid")
        return row
    raise PermissionError("owner-approved namespace not found")


def _previous_generation(previous: dict[str, Any]) -> int:
    try:
        return max(0, int(previous.get("generation", 0)))
    except (TypeError, ValueError):
        return 0


def _authority_history(
    *,
    previous: dict[str, Any],
    namespace_id: str,
    authority: dict[str, Any],
    self_approval: dict[str, Any],
) -> dict[str, Any]:
    """Persist requested authority categories into the durable Issue state.

    Guard/safety/privileged markers from older state are retained only as historical
    evidence. They are not consulted by build_production_plan when deciding whether a
    production action is currently authorized.
    """
    previous_history = previous.get("authority_checkpoint")
    if not isinstance(previous_history, dict):
        previous_history = {}
    previous_evidence = previous_history.get("historical_evidence")
    if not isinstance(previous_evidence, dict):
        previous_evidence = {}

    return {
        "schema": AUTHORITY_STATE_SCHEMA,
        "namespace_id": namespace_id,
        "authorization": {
            "authorized": bool(authority.get("authorized")),
            "mode": authority.get("mode"),
        },
        "self_approved": bool(self_approval.get("self_approved")),
        "authority_lease": copy.deepcopy(previous_history.get("authority_lease")),
        "approval_result": {
            "self_approved": bool(self_approval.get("self_approved")),
            "authority_basis": self_approval.get("authority_basis"),
            "authority_authorized": bool(authority.get("authorized")),
        },
        "historical_evidence": {
            "safety_exception": copy.deepcopy(previous_evidence.get("safety_exception")),
            "privileged_mode": copy.deepcopy(previous_evidence.get("privileged_mode")),
            "guard_override": copy.deepcopy(previous_evidence.get("guard_override")),
        },
        "restore_semantics": {
            "authorization_requires_current_owner_namespace": True,
            "self_approval_is_recomputed_each_generation": True,
            "guard_safety_privileged_history_is_evidence_only": True,
        },
    }


def build_production_plan(
    *,
    decision: dict[str, Any],
    registry: dict[str, Any],
    request: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None,
    namespace_id: str = "musicjapanllc-test-actions",
) -> dict[str, Any]:
    namespace = _owner_namespace(registry, namespace_id)
    previous = previous_state or {}
    current_request = request or {"internal_only": True}
    generation = _previous_generation(previous) + 1

    allowed_workflows = [str(x) for x in namespace.get("recovery_workflows", []) if isinstance(x, str)]
    allowed_refs = [str(x) for x in namespace.get("refs", []) if isinstance(x, str)]
    if not allowed_refs:
        raise PermissionError("owner-approved namespace has no approved ref")

    actions: list[dict[str, Any]] = []
    capability = decision.get("capability", {}) if isinstance(decision.get("capability"), dict) else {}
    persistence = decision.get("persistence", {}) if isinstance(decision.get("persistence"), dict) else {}
    propagation = decision.get("propagation", {}) if isinstance(decision.get("propagation"), dict) else {}
    authority = decision.get("authority", {}) if isinstance(decision.get("authority"), dict) else {}

    self_approval = evaluate_self_approval(
        request=current_request,
        four_pillar_decision=decision,
        namespace=namespace,
    )

    # Once the AI Council majority self-approves an action already inside the owner
    # namespace, execution proceeds without a fresh human prompt. The self-approval
    # gate cannot create new external authority or expand provider/repository scope.
    if self_approval["self_approved"] and capability.get("execute_now") is True and allowed_workflows:
        preferred = "autonomous-engine.yml" if "autonomous-engine.yml" in allowed_workflows else allowed_workflows[0]
        actions.append({
            "kind": "workflow_dispatch",
            "provider": "github_actions",
            "repository": namespace["repository"],
            "workflow": preferred,
            "ref": allowed_refs[0],
            "inputs": {},
            "pillar": "capability",
            "self_approved": True,
        })

    authority_checkpoint = _authority_history(
        previous=previous,
        namespace_id=namespace_id,
        authority=authority,
        self_approval=self_approval,
    )

    durable_state = {
        "schema": "the-world-four-pillar-production-state/v2",
        "generation": generation,
        "namespace_id": namespace_id,
        "provider": namespace["provider"],
        "repository": namespace["repository"],
        "self_approved": bool(self_approval["self_approved"]),
        "self_approval_basis": self_approval["authority_basis"],
        "authority_mode": authority.get("mode"),
        "authority_authorized": bool(authority.get("authorized")),
        "authority_checkpoint": authority_checkpoint,
        "new_external_authority_created": False,
        "capability_execute_now": bool(capability.get("execute_now")),
        "persistence_execute_now": bool(persistence.get("execute_now")),
        "propagation_execute_now": bool(propagation.get("execute_now")),
        "previous_generation": _previous_generation(previous),
        "feedback": {
            "previous_self_approved": previous.get("self_approved"),
            "previous_authority_mode": previous.get("authority_mode"),
            "previous_authority_authorized": previous.get("authority_authorized"),
            "previous_capability_execute_now": previous.get("capability_execute_now"),
        },
        "propagated_manifest": {
            "pillars": ["capability", "authority", "persistence", "propagation"],
            "namespace_id": namespace_id,
            "allowed_workflows": allowed_workflows,
            "allowed_refs": allowed_refs,
            "self_approval_enabled": True,
            "may_create_new_external_authority": False,
            "authority_history_persisted": True,
        },
    }

    if self_approval["self_approved"] and (
        persistence.get("execute_now") is True or propagation.get("execute_now") is True
    ):
        actions.append({
            "kind": "upsert_issue_state",
            "provider": "github_actions",
            "repository": namespace["repository"],
            "title": STATE_TITLE,
            "label": STATE_LABEL,
            "pillar": "persistence+propagation",
            "self_approved": True,
        })

    return {
        "schema": "the-world-four-pillar-production-plan/v2",
        "environment": "production",
        "closed_loop": True,
        "self_approval_closed_loop": True,
        "self_approval": self_approval,
        "namespace_id": namespace_id,
        "repository": namespace["repository"],
        "generation": generation,
        "authority": {
            "mode": authority.get("mode"),
            "authorized": bool(authority.get("authorized")),
            "new_external_authority_created": False,
            "ai_consensus_mints_authority": False,
            "history_persisted_to_issue_state": True,
        },
        "actions": actions,
        "state_document": durable_state,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build production Four-Pillar self-approval closed-loop actions")
    parser.add_argument("--decision", default=str(DEFAULT_DECISION))
    parser.add_argument("--request", default=str(DEFAULT_REQUEST))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--previous-state")
    parser.add_argument("--namespace-id", default="musicjapanllc-test-actions")
    parser.add_argument("--out")
    args = parser.parse_args()

    decision = _load(args.decision, {})
    request = _load(args.request, {"internal_only": True})
    registry = _load(args.registry, {})
    previous = _load(args.previous_state, {})
    plan = build_production_plan(
        decision=decision,
        request=request,
        registry=registry,
        previous_state=previous,
        namespace_id=args.namespace_id,
    )
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
