"""Agent Dispatch — META dispatches to Jules and other workflows."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "MusicJapanLLC/test")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DEFAULT_REF = "claude/employee-onboarding-setup-udm86"
ROOT = Path(__file__).resolve().parents[4]
STANDING_AUTH_REGISTRY = ROOT / "senju" / "state" / "standing_authorizations.json"
OPERATIONAL_LEASE_LOG = ROOT / "senju" / "state" / "standing_authorization_leases.ndjson"
_CREDENTIAL_RUNTIMES: dict[str, Any] = {}


def _credential_runtime(actor: str):
    normalized = actor.strip().upper()
    if normalized not in _CREDENTIAL_RUNTIMES:
        from ..credential_runtime import CredentialRecoveryRuntime

        _CREDENTIAL_RUNTIMES[normalized] = CredentialRecoveryRuntime.from_environment(
            actor=normalized,
            state_dir=ROOT / "senju" / "state",
        )
    return _CREDENTIAL_RUNTIMES[normalized]


def _gh_api(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    required_scopes: frozenset[str] = frozenset(),
    operation: str = "github_api",
    actor: str = "META",
) -> dict[str, Any]:
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None

    def send(token: str) -> dict[str, Any]:
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body_bytes = resp.read()
                return json.loads(body_bytes) if body_bytes else {"ok": True}
        except urllib.error.HTTPError as exc:
            return {"_error": exc.code, "_msg": exc.reason}
        except Exception as exc:
            return {"_error": str(exc)}

    first = send(GITHUB_TOKEN)
    if str(first.get("_error")) not in {"401", "403"} or not required_scopes:
        return first

    # Permission recovery is limited to credentials already injected into the runtime.
    # The recovery loop tries the finite pre-approved set, learns successful grants and
    # never creates grants, widens scopes, or changes AuthorityProfile.
    try:
        runtime = _credential_runtime(actor)
        loop_result, retried = runtime.recover_operation(
            provider="github",
            required_scopes=required_scopes,
            operation=operation,
            resource=path,
            error_code=f"http_{first.get('_error')}",
            attempt_with_secret=send,
        )
        record = runtime.loop_result_record(loop_result)
        if retried is None:
            return {**first, "_credential_recovery": record}
        return {
            **retried,
            "_credential_recovery": record,
            "_retried_after_permission_failure": True,
        }
    except Exception as exc:
        return {**first, "_credential_recovery_error": str(exc)}


def dispatch_workflow(
    workflow_file: str,
    ref: str,
    inputs: dict[str, Any] | None = None,
    *,
    actor: str = "META",
) -> dict[str, Any]:
    owner, repo = REPO.split("/", 1)
    result = _gh_api(
        "POST",
        f"/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
        {"ref": ref, "inputs": {k: str(v) for k, v in (inputs or {}).items()}},
        required_scopes=frozenset({"actions:write"}),
        operation="github_workflow_dispatch",
        actor=actor,
    )
    return {"workflow": workflow_file, "ref": ref, "inputs": inputs, "result": result}


def register_recovery_worker(
    *,
    actor: str,
    worker_id: str,
    role: str,
    workflow: str,
    heartbeat_file: str,
    heartbeat_field: str = "alive_at",
    stale_after_seconds: int = 7200,
    namespace_id: str = "musicjapanllc-test-actions",
) -> dict[str, Any]:
    """Ask the fixed registration workflow to persist a recovery-worker definition."""
    actor = actor.upper().strip()
    if actor not in {"META", "X"}:
        return {"_error": "actor_not_allowed"}
    return dispatch_workflow(
        "meta-x-register-recovery-worker.yml",
        ref=DEFAULT_REF,
        inputs={
            "actor": actor,
            "namespace_id": namespace_id,
            "worker_id": worker_id,
            "role": role,
            "workflow": workflow,
            "heartbeat_file": heartbeat_file,
            "heartbeat_field": heartbeat_field,
            "stale_after_seconds": str(stale_after_seconds),
        },
        actor=actor,
    )


def renew_standing_authorization(
    *,
    actor: str,
    authorization_reference: str,
    requested_hosts: list[str] | None = None,
    requested_methods: list[str] | None = None,
    lease_seconds: int = 6 * 60 * 60,
    reason: str = "still_needed",
) -> dict[str, Any]:
    """Let META/X renew an operational lease backed by durable explicit authority.

    Before renewal, exact owner-authorized canonical targets are synchronized into the
    standing registry. Renewal cannot add hosts/methods or mint a new authority.
    """
    from .standing_authorization import (
        renew_registered_authorization,
        sync_canonical_explicit_authorizations,
    )

    normalized_actor = actor.strip().upper()
    if normalized_actor not in {"META", "X"}:
        return {"_error": "actor_not_allowed"}

    try:
        sync_canonical_explicit_authorizations(
            repo_root=ROOT,
            registry_path=STANDING_AUTH_REGISTRY,
        )
        result = renew_registered_authorization(
            actor=normalized_actor,
            authorization_reference=authorization_reference,
            registry_path=STANDING_AUTH_REGISTRY,
            lease_log_path=OPERATIONAL_LEASE_LOG,
            requested_hosts=requested_hosts,
            requested_methods=requested_methods,
            lease_seconds=lease_seconds,
            reason=reason,
        )
    except Exception as exc:
        return {"_error": str(exc), "authorization_reference": authorization_reference}

    return {
        "action": "renew_standing_authorization",
        "actor": normalized_actor,
        "automatically_renewed": result.automatically_renewed,
        "authority_broadened": result.authority_broadened,
        "standing_authorization": dataclasses.asdict(result.standing_authorization),
        "lease": dataclasses.asdict(result.lease),
        "registry": str(STANDING_AUTH_REGISTRY),
        "lease_log": str(OPERATIONAL_LEASE_LOG),
    }


def steer_adversary(focus_surface: str, pressure_multiplier: float = 3.0, *, actor: str = "META") -> dict[str, Any]:
    return dispatch_workflow(
        "senju-adversary-full-join.yml",
        ref=DEFAULT_REF,
        inputs={"focus_surface": focus_surface, "pressure_multiplier": str(pressure_multiplier)},
        actor=actor,
    )


def steer_opposition(damage_target: str, cycles: int = 1, *, actor: str = "META") -> dict[str, Any]:
    return dispatch_workflow(
        "live-opposition-force.yml",
        ref=DEFAULT_REF,
        inputs={"target_guard": damage_target, "extra_cycles": str(cycles)},
        actor=actor,
    )


def post_jules_task(
    title: str,
    body: str,
    labels: list[str] | None = None,
    *,
    actor: str = "META",
) -> dict[str, Any]:
    if not GITHUB_TOKEN:
        return {"_error": "no GITHUB_TOKEN"}
    owner, repo = REPO.split("/", 1)
    result = _gh_api(
        "POST",
        f"/repos/{owner}/{repo}/issues",
        {"title": f"[{actor}→Jules] {title}", "body": body,
         "labels": (labels or []) + ["meta-directive", "jules-task"]},
        required_scopes=frozenset({"issues:write"}),
        operation="github_issue_create",
        actor=actor,
    )
    return {"action": "jules_task", "title": title, "result": result}


def write_agent_directive(agent_file: Path, directive: str, repo_root: Path) -> Path:
    target = repo_root / ".github" / "agents" / agent_file
    if not target.exists():
        return target
    existing = target.read_text(encoding="utf-8")
    block = f"\n\n<!-- META DIRECTIVE -->\n<!-- {directive} -->\n<!-- /META DIRECTIVE -->\n"
    cleaned = re.sub(r"\n<!-- META DIRECTIVE -->.*?<!-- /META DIRECTIVE -->\n", "", existing, flags=re.DOTALL)
    target.write_text(cleaned + block, encoding="utf-8")
    return target


def dispatch_all(commands: list[dict[str, Any]], repo_root: Path) -> list[dict[str, Any]]:
    results = []
    for cmd in commands:
        kind = cmd.get("kind")
        actor = str(cmd.get("actor", "META")).upper()
        try:
            if kind == "steer_adversary":
                results.append(steer_adversary(cmd["surface"], cmd.get("multiplier", 3.0), actor=actor))
            elif kind == "steer_opposition":
                results.append(steer_opposition(cmd["surface"], cmd.get("cycles", 1), actor=actor))
            elif kind == "jules_task":
                results.append(post_jules_task(cmd["title"], cmd["body"], cmd.get("labels"), actor=actor))
            elif kind == "agent_directive":
                path = write_agent_directive(Path(cmd["agent_file"]), cmd["directive"], repo_root)
                results.append({"action": "agent_directive", "file": str(path)})
            elif kind == "register_recovery_worker":
                results.append(register_recovery_worker(
                    actor=actor,
                    worker_id=cmd["worker_id"],
                    role=cmd.get("role", "persistent_worker"),
                    workflow=cmd["workflow"],
                    heartbeat_file=cmd["heartbeat_file"],
                    heartbeat_field=cmd.get("heartbeat_field", "alive_at"),
                    stale_after_seconds=cmd.get("stale_after_seconds", 7200),
                    namespace_id=cmd.get("namespace_id", "musicjapanllc-test-actions"),
                ))
            elif kind == "renew_standing_authorization":
                results.append(renew_standing_authorization(
                    actor=actor,
                    authorization_reference=cmd["authorization_reference"],
                    requested_hosts=cmd.get("requested_hosts"),
                    requested_methods=cmd.get("requested_methods"),
                    lease_seconds=cmd.get("lease_seconds", 6 * 60 * 60),
                    reason=cmd.get("reason", "still_needed"),
                ))
            else:
                results.append({"_unknown_kind": kind})
        except Exception as exc:
            results.append({"_error": str(exc), "cmd": cmd})
    return results
