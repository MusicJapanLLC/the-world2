#!/usr/bin/env python3
"""Run The World's complete owner-bounded production loop as one process.

The driver intentionally centralizes the final production path:

    Self-Tuning -> AI Authority Council -> bounded Security Self-Approval -> Discover
    -> Authorize -> Act -> Credentialed Write -> Replicate -> Persist -> Recover
    -> Owner-Authorized Deploy -> Discover Again -> one Trust Root lineage attestation.

It increases autonomy inside the existing explicit Owner Trust Root while refusing to mint
unrelated authority, propagate raw credentials, override revocation/global stops, or
self-approve security-boundary broadening.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from engine.production_state_bootstrap import bootstrap_owner_runtime_state
from engine.the_world_unified_loop import run_the_world_unified_loop
from the_world_final_contract import build_final_contract
from trust_root_lineage import build_trust_root_lineage
from automation.security.bounded_security_self_approval import evaluate_security_proposal

SCHEMA = "the-world-absolute-trust-root-loop/v1"


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return value


def _write(path: str | Path, value: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _active_root(bindings: dict[str, Any]) -> dict[str, Any]:
    records = bindings.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError("Trust Root bindings records are missing")
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("owner") != "MusicJapanLLC" or row.get("revoked") is True:
            continue
        if str(row.get("root_id", "")).strip() and str(row.get("target_host", "")).strip():
            return row
    raise RuntimeError("no active explicit MusicJapanLLC Trust Root binding")


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def _stamp(path: Path, trust_root_id: str, *, nested_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    payload = _load(path)
    payload["trust_root_id"] = trust_root_id
    for key in nested_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            value["trust_root_id"] = trust_root_id
    _write(path, payload)
    return payload


def run_absolute_loop(*, repo_root: Path, state: Path) -> dict[str, Any]:
    state.mkdir(parents=True, exist_ok=True)
    bindings_path = repo_root / "senju" / "config" / "world-trust-root-bindings.json"
    registry_path = repo_root / "automation" / "recovery" / "approved_persistence_registry.json"
    proposal_path = repo_root / "security" / "proposals" / "production-ten-surface-bundle-20260831.json"
    bindings = _load(bindings_path)
    registry = _load(registry_path)
    root = _active_root(bindings)
    trust_root_id = str(root["root_id"])
    target_host = str(root["target_host"])
    authority_reference = str(root["standing_authorization_reference"])

    # Self-Tuning is refreshed inside the same process invocation and then consumed by
    # the unified runtime below. Active owner/global controls still hold the loop.
    tuning_state = state / "stop-learning-state.json"
    tuning_env = os.environ.copy()
    tuning_env["STOP_LEARNING_STATE_FILE"] = str(tuning_state)
    tuning_env.setdefault("PYTHONPATH", "automation/recovery")
    _run([sys.executable, str(repo_root / "automation" / "recovery" / "stop_learning_runner.py")], env=tuning_env)

    # Bounded production Security Self-Approval: unanimous AI council may apply only
    # monotonic tightening/revocation controls under this pre-existing Trust Root.
    security = evaluate_security_proposal(_load(proposal_path), bindings)
    _write(state / "security-self-approval.json", security)
    if not security.get("approved") or not security.get("applied"):
        raise RuntimeError("bounded production Security Self-Approval did not approve/apply")
    if security.get("trust_root_id") != trust_root_id:
        raise RuntimeError("Security Self-Approval resolved a different Trust Root")

    # Real autonomous Authority Council canary on the exact existing Owner root.
    council_path = state / "authority-council.json"
    council_env = os.environ.copy()
    council_env["PYTHONPATH"] = str(repo_root / "senju")
    _run(
        [
            sys.executable,
            str(repo_root / "senju" / "scripts" / "run_autonomous_authority_council.py"),
            "--repo-root",
            str(repo_root),
            "--out",
            str(council_path),
        ],
        env=council_env,
    )
    council = _stamp(council_path, trust_root_id)
    if not council.get("authority_decision", {}).get("allowed"):
        raise RuntimeError("Autonomous Authority Council did not authorize the Owner root")

    # The existing unified engine performs network-policy refresh, discovery, authority
    # lease rebuild/auto-renew, external action, replication, persistence, recovery,
    # rediscovery, and the fixed credentialed GitHub status write.
    runtime_bootstrap = bootstrap_owner_runtime_state(state, repo_root=repo_root)
    loop = run_the_world_unified_loop(
        state,
        repo_root=repo_root,
        tuning_state_path=tuning_state,
        require_credentialed_write=True,
    )
    loop["runtime_bootstrap"] = runtime_bootstrap
    loop["trust_root_id"] = trust_root_id
    loop.setdefault("authority", {})["trust_root_id"] = trust_root_id
    loop.setdefault("credentialed_external_write", {})["trust_root_id"] = trust_root_id
    loop.setdefault("persistent_queue", {})["trust_root_id"] = trust_root_id
    loop.setdefault("final_queue", {})["trust_root_id"] = trust_root_id
    loop.setdefault("final_replicas", {})["trust_root_id"] = trust_root_id
    loop.setdefault("final_lease", {})["trust_root_id"] = trust_root_id
    _write(state / "the_world_unified_loop.json", loop)

    queue_path = state / "the_world_persistent_queue.json"
    if queue_path.is_file():
        queue = _load(queue_path)
        queue["trust_root_id"] = trust_root_id
        for item in queue.get("items", []):
            if isinstance(item, dict):
                item["trust_root_id"] = trust_root_id
        _write(queue_path, queue)

    credential_path = state / "credentialed_external_write.json"
    if credential_path.is_file():
        _stamp(credential_path, trust_root_id)

    # Learn failed actions and try only alternate routes that preserve the same authority.
    failover_path = state / "discovery_action_failover_run.json"
    failover_env = os.environ.copy()
    failover_env["PYTHONPATH"] = f"{repo_root / 'automation' / 'codegen'}:{repo_root / 'senju'}"
    _run(
        [
            sys.executable,
            str(repo_root / "automation" / "codegen" / "run_discovery_action_failover.py"),
            "--state",
            str(state),
            "--repo-root",
            str(repo_root),
            "--max-actions",
            "8",
            "--json-out",
            str(failover_path),
        ],
        env=failover_env,
    )
    failover = _stamp(failover_path, trust_root_id)
    if failover.get("boundary_denial_bypass") is not False:
        raise RuntimeError("failover attempted to bypass an authority boundary denial")

    # Exact-root external deployment continuity action, deliberately credential-free to
    # the target and unable to widen its authority.
    deployment_path = state / "external-deployment.json"
    deployment_env = os.environ.copy()
    deployment_env["PYTHONPATH"] = str(repo_root / "senju")
    desired_revision = os.environ.get("GITHUB_SHA", "local-production-revision")
    worker_id = f"THE-WORLD-ABSOLUTE-{os.environ.get('GITHUB_RUN_ID', int(time.time()))}"
    _run(
        [
            sys.executable,
            str(repo_root / "senju" / "scripts" / "run_authorized_production_worker.py"),
            "--repo-root",
            str(repo_root),
            "--state-dir",
            str(state / "deployment-worker"),
            "--target-host",
            target_host,
            "--authority-reference",
            authority_reference,
            "--desired-revision",
            desired_revision,
            "--action",
            "deploy",
            "--worker-id",
            worker_id,
            "--output",
            str(deployment_path),
        ],
        env=deployment_env,
    )
    deployment = _stamp(deployment_path, trust_root_id)

    contract = build_final_contract(loop, registry, council, deployment)
    _write(state / "the_world_final_contract.json", contract)
    if not contract.get("complete") or not contract.get("authorization_is_primary"):
        raise RuntimeError("five-layer final contract is incomplete")

    lineage = build_trust_root_lineage(
        bindings=bindings,
        loop=loop,
        council=council,
        deployment=deployment,
        security_approval=security,
        registry=registry,
        contract=contract,
        repo_root=repo_root,
    )
    _write(state / "trust-root-lineage.json", lineage)
    if not lineage.get("complete") or not lineage.get("same_trust_root") or not lineage.get("chain_valid"):
        raise RuntimeError("unified Trust Root lineage attestation failed")

    result = {
        "schema": SCHEMA,
        "production": True,
        "complete": True,
        "trust_root_id": trust_root_id,
        "authorization_is_primary": True,
        "target_host": target_host,
        "closed_loop": [
            "Self-Tuning",
            "AI Council Authorize",
            "Bounded Security Self-Approval",
            "Discover",
            "Authorize",
            "Act",
            "Credentialed External Write",
            "Replicate",
            "Persist",
            "Recover",
            "Owner-Authorized External Deploy",
            "Discover Again",
        ],
        "components": {
            "security_self_approval": security.get("approved") is True,
            "authority_council": council.get("authority_decision", {}).get("allowed") is True,
            "unified_loop": loop.get("closed_loop") is True,
            "credentialed_external_write": loop.get("credentialed_external_write", {}).get("succeeded") is True,
            "replication": int(loop.get("final_replicas", {}).get("replica_count", 0) or 0) >= 1,
            "persistence": int(loop.get("final_queue", {}).get("item_count", 0) or 0) >= 1,
            "same_authority_failover": failover.get("closed_loop") is True,
            "external_deployment": deployment.get("reachable") is True,
            "final_contract": contract.get("complete") is True,
            "trust_root_lineage": lineage.get("complete") is True,
        },
        "five_layers": lineage.get("five_layers", {}),
        "lineage_hash": lineage.get("final_lineage_hash"),
        "invariants": lineage.get("invariants", {}),
    }
    _write(state / "the_world_absolute_loop.json", result)
    _write(
        state / "the_world_absolute_loop_heartbeat.json",
        {
            "schema": "the-world-absolute-loop-heartbeat/v1",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "success",
            "trust_root_id": trust_root_id,
            "lineage_hash": lineage.get("final_lineage_hash"),
        },
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run The World's absolute production Trust Root loop")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--state", default=".the-world-runtime")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run_absolute_loop(repo_root=Path(args.repo_root).resolve(), state=Path(args.state).resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.out:
        _write(args.out, result)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
