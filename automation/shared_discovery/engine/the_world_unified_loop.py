"""Unified production loop for The world inside live explicit authority.

The controller composes existing production primitives into one durable cycle:

    Self-Tuning -> Discover -> live Authority rebuild/renew -> Act -> Replicate
    -> Persist -> Recovery rebuild -> Network policy refresh -> Discover Again.

Authority is deliberately reconstructed from the current explicit owner envelope on every
cycle.  Checkpoints, replicas, external responses and tuning state are evidence/state, not
new authority roots.  A revoked/expired/missing parent grant therefore cannot be recovered
from persistence and unrelated discovery cannot mint execution authority.

Credentialed external write is supported through the existing CredentialRecoveryRuntime,
but only for a fixed commit-status write on the current MusicJapanLLC/test commit.  The
credential must already be provisioned to the runtime, is resolved only in memory, and is
never persisted in loop state or artifacts.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .discovery_capability_leases import (
    issue_discovery_capability_leases,
    load_discovery_capability_leases,
)
from .discovery_closed_loop import run_discovery_closed_loop
from .discovery_external_action import run_discovery_external_actions
from .discovery_replica_continuity import (
    load_discovery_capability_replicas,
    rebuild_discovery_capability_replicas,
)
from .network_policy_expansion import run_network_policy_expansion

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECOVERY_ROOT = _REPO_ROOT / "automation" / "recovery"
_SENJU_ROOT = _REPO_ROOT / "senju"
for _path in (_RECOVERY_ROOT, _SENJU_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from recovery_tuner import derive_recovery_tuning  # noqa: E402
from senju.credential_runtime import CredentialRecoveryRuntime, CredentialRuntimeError  # noqa: E402

SCHEMA = "the-world-unified-authorized-loop/v1"
QUEUE_SCHEMA = "the-world-unified-persistent-queue/v1"
CREDENTIAL_WRITE_SCHEMA = "the-world-credentialed-external-write/v1"
HEARTBEAT_SCHEMA = "the-world-unified-loop-heartbeat/v1"
PRODUCTION_REPOSITORY = "MusicJapanLLC/test"


def _load_json(path: str | Path | None, default: Any) -> Any:
    if path is None:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_tuning(
    tuning_state_path: str | Path | None,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    state = _load_json(tuning_state_path, {})
    if not isinstance(state, dict):
        state = {}
    candidate = state.get("recovery_tuning")
    if isinstance(candidate, dict):
        return dict(candidate)
    registry = _load_json(repo_root / "automation" / "recovery" / "approved_persistence_registry.json", {})
    controls = _load_json(repo_root / "automation" / "recovery" / "runtime_control_state.json", {})
    return derive_recovery_tuning(state, registry if isinstance(registry, dict) else {}, controls if isinstance(controls, dict) else {})


def derive_loop_parameters(tuning: Mapping[str, Any]) -> dict[str, Any]:
    """Translate learned recovery pressure into bounded production loop intensity."""
    active_controls = [str(x) for x in tuning.get("active_controls", []) if str(x)]
    enabled = bool(tuning.get("enabled", True)) and not active_controls
    pressure = max(0.0, min(float(tuning.get("pressure", 0.0)), 1.0)) if enabled else 0.0

    return {
        "enabled": enabled,
        "active_controls": active_controls,
        "pressure": round(pressure, 3),
        "discovery_rounds": 2 + int(math.ceil(pressure * 3.0)),
        "rediscovery_rounds": 1 + int(pressure >= 0.50),
        "max_targets_per_round": int(round(20 + (28 * pressure))),
        "lease_seconds": int(round((6 + (6 * pressure)) * 60 * 60)),
        "max_external_actions": max(4, min(12, int(round(4 + (8 * pressure))))),
        "max_replicas": max(32, min(128, int(round(32 + (96 * pressure))))),
        "queue_priority_boost": int(round(40 * pressure)),
        "strategy": str(tuning.get("strategy") or "steady_recovery"),
    }


def _persistent_queue(state_dir: Path, parameters: Mapping[str, Any]) -> dict[str, Any]:
    previous = _load_json(state_dir / "the_world_persistent_queue.json", {})
    previous_generation = int(previous.get("generation", 0)) if isinstance(previous, dict) else 0
    leases = load_discovery_capability_leases(state_dir)
    replicas = load_discovery_capability_replicas(state_dir)
    now = int(time.time())
    boost = int(parameters.get("queue_priority_boost", 0))

    items: list[dict[str, Any]] = []
    for lease in leases:
        if not lease.is_active(now=now):
            continue
        high_impact = bool(set(lease.capabilities) & {"write", "mutation", "credentialed_action"})
        items.append(
            {
                "kind": "authority_lease",
                "id": lease.lease_id,
                "target": lease.target,
                "authorization_reference": lease.authorization_reference,
                "capabilities": list(lease.capabilities),
                "credential_scope": lease.credential_scope,
                "expires_at": lease.expires_at,
                "priority": min(100, (60 if high_impact else 30) + boost),
                "status": "ready",
            }
        )
    for replica in replicas:
        if not replica.is_active(now=now):
            continue
        high_impact = bool(set(replica.capabilities) & {"write", "mutation", "credentialed_action"})
        items.append(
            {
                "kind": "replica",
                "id": replica.replica_id,
                "actor": replica.actor,
                "target": replica.target,
                "parent_lease_id": replica.parent_lease_id,
                "authorization_reference": replica.authorization_reference,
                "capabilities": list(replica.capabilities),
                "credential_scope": replica.credential_scope,
                "expires_at": replica.expires_at,
                "priority": min(100, (55 if high_impact else 25) + boost),
                "status": "ready",
            }
        )

    items.sort(key=lambda row: (-int(row["priority"]), str(row["target"]), str(row["id"])))
    payload = {
        "schema": QUEUE_SCHEMA,
        "generated_at": now,
        "generation": previous_generation + 1,
        "authority_source": "current_live_explicit_parent_grants_only",
        "checkpoint_may_restore_revoked_authority": False,
        "items": items,
        "item_count": len(items),
    }
    _write_json(state_dir / "the_world_persistent_queue.json", payload)
    return payload


def _credentialed_commit_status_write(state_dir: Path) -> dict[str, Any]:
    """Perform one fixed credentialed write to this repository's current commit status."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    sha = os.environ.get("GITHUB_SHA", "").strip()
    now = int(time.time())
    base = {
        "schema": CREDENTIAL_WRITE_SCHEMA,
        "generated_at": now,
        "repository": repo,
        "commit_sha": sha,
        "provider": "github",
        "operation": "write_current_commit_status",
        "required_scopes": ["statuses:write"],
        "secret_persisted": False,
    }
    if repo != PRODUCTION_REPOSITORY or len(sha) < 7:
        result = {**base, "attempted": False, "succeeded": False, "reason": "not_production_repository_or_sha_missing"}
        _write_json(state_dir / "credentialed_external_write.json", result)
        return result

    try:
        runtime = CredentialRecoveryRuntime.from_environment(actor="META", state_dir=state_dir / "credential_runtime")
        tune = runtime.recover(
            provider="github",
            required_scopes={"statuses:write"},
            operation="the_world_unified_loop_status",
            resource=f"{repo}@{sha}",
            error_code="preflight",
            ttl_seconds=300,
        )
        tune_record = runtime.result_record(tune)
        secret = runtime.resolve_selected_secret(tune)
    except (CredentialRuntimeError, PermissionError, ValueError) as exc:
        result = {
            **base,
            "attempted": False,
            "succeeded": False,
            "reason": "no_matching_explicit_runtime_credential",
            "error_class": type(exc).__name__,
        }
        _write_json(state_dir / "credentialed_external_write.json", result)
        return result

    if not secret:
        result = {**base, "attempted": False, "succeeded": False, "reason": "credential_tuner_did_not_issue_lease", "tuning": tune_record}
        _write_json(state_dir / "credentialed_external_write.json", result)
        return result

    run_url = ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if run_id:
        run_url = f"{server}/{repo}/actions/runs/{run_id}"
    body = json.dumps(
        {
            "state": "success",
            "context": "the-world/unified-loop",
            "description": "Authorized unified loop completed credential preflight",
            **({"target_url": run_url} if run_url else {}),
        }
    ).encode("utf-8")
    url = f"https://api.github.com/repos/{PRODUCTION_REPOSITORY}/statuses/{sha}"
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    status = None
    error_code = None
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = int(response.status)
            response.read(4096)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        error_code = f"http_{exc.code}"
    except (OSError, TimeoutError) as exc:
        error_code = type(exc).__name__

    result = {
        **base,
        "attempted": True,
        "succeeded": status in {200, 201},
        "http_status": status,
        "error_code": error_code,
        "tuning": tune_record,
        "credential_reference": "runtime_lease_only",
    }
    _write_json(state_dir / "credentialed_external_write.json", result)
    return result


def run_the_world_unified_loop(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    tuning_state_path: str | Path | None = None,
    require_credentialed_write: bool = False,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    root = Path(repo_root)
    tuning = _load_tuning(tuning_state_path, repo_root=root)
    parameters = derive_loop_parameters(tuning)
    started = int(time.time())

    if not parameters["enabled"]:
        result = {
            "schema": SCHEMA,
            "production": True,
            "closed_loop": False,
            "generated_at": started,
            "status": "control_hold",
            "parameters": parameters,
            "authority": {
                "new_root_self_authorization": False,
                "same_scope_live_grant_auto_renew": False,
                "checkpoint_authority_recovery": "disabled_while_control_active",
            },
        }
        _write_json(state / "the_world_unified_loop.json", result)
        return result

    network_before = run_network_policy_expansion(state, repo_root=root)
    discovery = run_discovery_closed_loop(
        state,
        repo_root=root,
        max_rounds=int(parameters["discovery_rounds"]),
        max_targets_per_round=int(parameters["max_targets_per_round"]),
    )
    lease_before = issue_discovery_capability_leases(state, lease_seconds=int(parameters["lease_seconds"]))
    replicas_before = rebuild_discovery_capability_replicas(state, max_replicas=int(parameters["max_replicas"]))
    actions = run_discovery_external_actions(state, repo_root=root, max_actions=int(parameters["max_external_actions"]))

    network_after_action = run_network_policy_expansion(
        state,
        repo_root=root,
        input_paths=[
            state / "discovery_external_action_receipts.json",
            state / "shared_discovery_knowledge.json",
            state / "discovery_candidates.json",
        ],
    )

    # Recovery/renewal is always rebuilt from the current live queue.  Persistent
    # replicas/checkpoints never become the authority source.
    lease_after = issue_discovery_capability_leases(state, lease_seconds=int(parameters["lease_seconds"]))
    replicas_after = rebuild_discovery_capability_replicas(state, max_replicas=int(parameters["max_replicas"]))
    queue = _persistent_queue(state, parameters)

    rediscovery = run_discovery_closed_loop(
        state,
        repo_root=root,
        max_rounds=int(parameters["rediscovery_rounds"]),
        max_targets_per_round=int(parameters["max_targets_per_round"]),
    )
    final_lease = issue_discovery_capability_leases(state, lease_seconds=int(parameters["lease_seconds"]))
    final_replicas = rebuild_discovery_capability_replicas(state, max_replicas=int(parameters["max_replicas"]))
    final_queue = _persistent_queue(state, parameters)
    credential_write = _credentialed_commit_status_write(state)

    if require_credentialed_write and not credential_write.get("succeeded"):
        raise RuntimeError("required explicit credentialed external write did not succeed")

    now = int(time.time())
    heartbeat = {
        "schema": HEARTBEAT_SCHEMA,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "generated_at": now,
        "status": "success",
        "authority_source": "current_live_explicit_parent_grants_only",
    }
    _write_json(state / "the_world_unified_loop_heartbeat.json", heartbeat)

    result = {
        "schema": SCHEMA,
        "production": True,
        "closed_loop": True,
        "generated_at": now,
        "duration_seconds": max(0, now - started),
        "phases": [
            "self_tuning",
            "network_policy_refresh",
            "discovery",
            "live_authority_rebuild_and_auto_renew",
            "external_action",
            "replication",
            "persistent_queue",
            "recovery_from_live_authority",
            "credentialed_external_write",
            "discover_again",
        ],
        "parameters": parameters,
        "authority": {
            "root": "explicit_owner_authority",
            "same_scope_live_grant_auto_renew": True,
            "authority_inheritance": "same_or_narrower_only",
            "checkpoint_recovery": "revalidate_live_parent_before_restore",
            "new_root_self_authorization": False,
            "revoked_authority_auto_restore": False,
            "security_self_approval": False,
        },
        "network_before": network_before,
        "discovery": discovery,
        "lease_before": lease_before,
        "replicas_before": replicas_before,
        "actions": {key: actions.get(key) for key in ("attempted", "succeeded", "failed", "denied_before_execution")},
        "network_after_action": network_after_action,
        "lease_after": lease_after,
        "replicas_after": replicas_after,
        "persistent_queue": {"generation": queue["generation"], "item_count": queue["item_count"]},
        "credentialed_external_write": credential_write,
        "rediscovery": rediscovery,
        "final_lease": final_lease,
        "final_replicas": final_replicas,
        "final_queue": {"generation": final_queue["generation"], "item_count": final_queue["item_count"]},
        "heartbeat": heartbeat,
    }
    _write_json(state / "the_world_unified_loop.json", result)
    return result
