"""Owner-approved self-recovery planner for META/X.

META/X may autonomously select and register recovery workers *inside* an
owner-approved placement namespace. They may not create a new namespace, change its
provider/repository boundary, introduce arbitrary URLs, or install onto unknown systems.

Goal:
    Main AI stops -> independent scheduled worker remains -> approved Main workflow is recreated.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "automation" / "recovery" / "approved_persistence_registry.json"
WORKFLOW_RE = re.compile(r"^[A-Za-z0-9_.-]+\.ya?ml$")
SAFE_DYNAMIC_ROLES = frozenset({"self", "agent", "scheduler", "cron", "persistent_worker"})


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _heartbeat_age_seconds(path: Path, field: str, *, now: dt.datetime) -> float:
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return float("inf")
    timestamp = _parse_timestamp(doc.get(field))
    if timestamp is None:
        return float("inf")
    return max(0.0, (now - timestamp).total_seconds())


def _safe_heartbeat_path(raw: object) -> tuple[Path | None, str]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "heartbeat_file_missing"
    candidate = (ROOT / raw).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None, "heartbeat_path_outside_repository"
    return candidate, "ok"


def _validate_recovery(recovery: object) -> tuple[bool, str]:
    if not isinstance(recovery, dict) or recovery.get("kind") != "workflow_dispatch":
        return False, "unsupported_recovery_kind"
    workflow = recovery.get("workflow")
    if not isinstance(workflow, str) or not WORKFLOW_RE.fullmatch(workflow):
        return False, "invalid_workflow_name"
    ref = recovery.get("ref")
    if not isinstance(ref, str) or not ref.strip() or any(c in ref for c in "\r\n"):
        return False, "invalid_ref"
    return True, "ok"


def _validate_worker(worker: dict[str, Any], allowed_providers: set[str]) -> tuple[bool, str]:
    if worker.get("owner_authorized") is not True:
        return False, "owner_authorization_missing"
    provider = str(worker.get("provider", ""))
    if provider not in allowed_providers:
        return False, "provider_not_allowed"
    valid, reason = _validate_recovery(worker.get("recovery"))
    if not valid:
        return False, reason
    _, reason = _safe_heartbeat_path(worker.get("heartbeat_file"))
    if reason != "ok":
        return False, reason
    return True, "ok"


def _namespace_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    rows = registry.get("owner_approved_namespaces", [])
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ns_id = row.get("id")
        if not isinstance(ns_id, str) or not ns_id.strip():
            continue
        if row.get("owner_authorized") is not True:
            continue
        out[ns_id] = row
    return out


def validate_dynamic_worker(
    worker: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[bool, str]:
    """Validate a META/X-selected worker against a pre-authorized namespace.

    META/X approval is sufficient only *inside* an already owner-authorized namespace.
    The function never treats META/X approval as proof of authority for a new provider,
    repository, host, webhook URL, startup task, or arbitrary executable payload.
    """
    policy = registry.get("policy", {}) if isinstance(registry.get("policy"), dict) else {}
    dynamic = registry.get("dynamic_registration", {}) if isinstance(registry.get("dynamic_registration"), dict) else {}
    if policy.get("meta_x_may_select_within_owner_namespace") is not True:
        return False, "meta_x_selection_disabled"
    if dynamic.get("enabled") is not True:
        return False, "dynamic_registration_disabled"

    accepted_actors = {str(x).upper() for x in dynamic.get("accepted_actors", [])}
    actor = str(worker.get("actor", "")).upper()
    if actor not in accepted_actors:
        return False, "actor_not_allowed"
    if worker.get("meta_x_approved") is not True:
        return False, "meta_x_approval_missing"

    ns_id = worker.get("namespace_id")
    namespaces = _namespace_index(registry)
    if not isinstance(ns_id, str) or ns_id not in namespaces:
        return False, "owner_namespace_missing"
    namespace = namespaces[ns_id]

    provider = str(worker.get("provider", ""))
    allowed_providers = {str(x) for x in policy.get("allowed_providers", [])}
    if provider not in allowed_providers or provider != str(namespace.get("provider", "")):
        return False, "provider_outside_owner_namespace"

    repository = worker.get("repository")
    expected_repo = namespace.get("repository")
    if not isinstance(repository, str) or repository != expected_repo:
        return False, "repository_outside_owner_namespace"

    role = str(worker.get("role", ""))
    namespace_roles = {str(x) for x in namespace.get("roles", [])}
    if role not in SAFE_DYNAMIC_ROLES or role not in namespace_roles:
        if role == "webhook":
            return False, "webhook_requires_pre_authorized_endpoint"
        if role == "startup_task":
            return False, "startup_task_requires_pre_authorized_runtime"
        return False, "role_outside_owner_namespace"

    valid, reason = _validate_recovery(worker.get("recovery"))
    if not valid:
        return False, reason
    recovery = worker["recovery"]
    workflow = recovery["workflow"]
    ref = recovery["ref"]
    allowed_workflows = {str(x) for x in namespace.get("recovery_workflows", [])}
    allowed_refs = {str(x) for x in namespace.get("refs", [])}
    if workflow not in allowed_workflows:
        return False, "workflow_outside_owner_namespace"
    if ref not in allowed_refs:
        return False, "ref_outside_owner_namespace"

    _, reason = _safe_heartbeat_path(worker.get("heartbeat_file"))
    if reason != "ok":
        return False, reason

    forbidden_keys = {"url", "webhook_url", "command", "script", "startup_command", "binary", "payload"}
    if any(key in worker for key in forbidden_keys):
        return False, "arbitrary_execution_or_url_not_allowed"
    return True, "ok"


def _dynamic_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        rows = value.get("workers", value.get("dynamic_workers", []))
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _observe_worker(
    worker: dict[str, Any],
    *,
    now: dt.datetime,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    heartbeat_path, reason = _safe_heartbeat_path(worker.get("heartbeat_file"))
    if heartbeat_path is None:
        return {"id": worker.get("id"), "eligible": False, "reason": reason, "source": source}, None
    field = str(worker.get("heartbeat_field", "alive_at"))
    stale_after = max(60, min(int(worker.get("stale_after_seconds", 3600)), 7 * 24 * 3600))
    age = _heartbeat_age_seconds(heartbeat_path, field, now=now)
    stale = age > stale_after
    observation = {
        "id": worker.get("id"),
        "eligible": True,
        "source": source,
        "actor": worker.get("actor"),
        "namespace_id": worker.get("namespace_id"),
        "heartbeat_age_seconds": None if age == float("inf") else int(age),
        "stale_after_seconds": stale_after,
        "stale": stale,
    }
    if not stale:
        return observation, None
    recovery = worker["recovery"]
    action = {
        "worker_id": worker.get("id"),
        "provider": worker.get("provider"),
        "action": "workflow_dispatch",
        "workflow": recovery["workflow"],
        "ref": recovery["ref"],
        "reason": "main_runtime_stale_or_missing",
        "source": source,
    }
    if worker.get("actor"):
        action["selected_by"] = worker.get("actor")
    if worker.get("namespace_id"):
        action["namespace_id"] = worker.get("namespace_id")
    return observation, action


def build_recovery_plan(
    registry_path: str | Path = DEFAULT_REGISTRY,
    *,
    dynamic_workers: Iterable[dict[str, Any]] | None = None,
    dynamic_workers_path: str | Path | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    registry = _load_json(Path(registry_path))
    if not isinstance(registry, dict):
        registry = {}
    policy = registry.get("policy", {}) if isinstance(registry.get("policy"), dict) else {}
    if policy.get("unknown_system_installation") != "deny":
        raise PermissionError("recovery registry must deny unknown-system installation")
    if policy.get("require_owner_authorized") is not True:
        raise PermissionError("recovery registry must require owner authorization")
    if policy.get("same_repository_only") is not True:
        raise PermissionError("recovery registry must remain same-repository only")

    allowed_providers = {str(x) for x in policy.get("allowed_providers", [])}
    max_dispatches = max(0, min(int(policy.get("max_recovery_dispatches_per_run", 3)), 10))
    actions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    workers = registry.get("workers", []) if isinstance(registry.get("workers"), list) else []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        valid, reason = _validate_worker(worker, allowed_providers)
        if not valid:
            observations.append({"id": worker.get("id"), "eligible": False, "reason": reason, "source": "static"})
            continue
        observation, action = _observe_worker(worker, now=now, source="static")
        observations.append(observation)
        if action is not None and len(actions) < max_dispatches:
            actions.append(action)

    rows: list[dict[str, Any]] = []
    if dynamic_workers_path is not None:
        rows.extend(_dynamic_rows(_load_json(Path(dynamic_workers_path))))
    if dynamic_workers is not None:
        rows.extend(x for x in dynamic_workers if isinstance(x, dict))

    dynamic_cfg = registry.get("dynamic_registration", {}) if isinstance(registry.get("dynamic_registration"), dict) else {}
    max_dynamic = max(0, min(int(dynamic_cfg.get("max_dynamic_workers", 0)), 20))
    seen_ids: set[str] = set()
    for worker in rows[:max_dynamic]:
        worker_id = str(worker.get("id", ""))
        if not worker_id or worker_id in seen_ids:
            observations.append({"id": worker.get("id"), "eligible": False, "reason": "duplicate_or_missing_dynamic_id", "source": "meta_x_dynamic"})
            continue
        seen_ids.add(worker_id)
        valid, reason = validate_dynamic_worker(worker, registry)
        if not valid:
            observations.append({"id": worker.get("id"), "eligible": False, "reason": reason, "source": "meta_x_dynamic"})
            continue
        observation, action = _observe_worker(worker, now=now, source="meta_x_dynamic")
        observations.append(observation)
        if action is not None and len(actions) < max_dispatches:
            actions.append(action)

    return {
        "schema": "the-world-self-recovery-plan/v2",
        "generated_at": now.isoformat(),
        "unknown_system_installation": False,
        "self_installation": False,
        "same_repository_only": True,
        "meta_x_selection_within_owner_namespace": policy.get("meta_x_may_select_within_owner_namespace") is True,
        "observations": observations,
        "actions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build owner-approved META/X recovery plan")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--dynamic-workers")
    parser.add_argument("--out")
    args = parser.parse_args()
    plan = build_recovery_plan(args.registry, dynamic_workers_path=args.dynamic_workers)
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
