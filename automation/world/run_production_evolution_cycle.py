#!/usr/bin/env python3
"""Run one bounded production evolution generation from a durable checkpoint.

This runner is designed for scheduled GitHub Actions execution. It restores the
last checkpoint, performs one production evolution generation, automatically
issues a fresh non-delegable replica lease, and writes the next checkpoint.
Replica authority inheritance is mandatory when configured: every replica must
carry a valid lease before the closed production cycle may advance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from automation.world.production_evolution_loop import (
    EvolutionState,
    ProductionEvolutionEnvelope,
    ProductionEvolutionLoop,
)
from automation.world.replica_authority import (
    issue_nondelegable_replica_lease,
    select_replica_profile,
)


def _id(*parts: object, length: int = 24) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def load_plan(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "production-evolution-auto-cycle/v1":
        raise ValueError("unsupported production evolution plan schema")
    return data


def load_state(path: Path, plan: Mapping[str, Any]) -> EvolutionState:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        leases_raw = data.get("worker_authority_leases") or []
        leases: list[tuple[str, str]] = []
        for item in leases_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                leases.append((str(item[0]), str(item[1])))
        return EvolutionState(
            generation=int(data.get("generation", 0)),
            worker_ids=tuple(str(v) for v in data.get("worker_ids") or ()),
            authority_profile=str(data.get("authority_profile") or ""),
            deploys_today=int(data.get("deploys_today", 0)),
            previous_checkpoint_id=str(data.get("checkpoint_id") or "") or None,
            worker_authority_leases=tuple(leases),
        )

    return EvolutionState(
        generation=0,
        worker_ids=tuple(str(v) for v in plan.get("initial_worker_ids") or ("META",)),
        authority_profile=str(plan.get("initial_authority_profile") or "base"),
        deploys_today=0,
        previous_checkpoint_id=None,
        worker_authority_leases=(),
    )


def _assert_mandatory_replica_leases(state: EvolutionState) -> None:
    """Fail closed if any non-root replica reached a checkpoint without a lease."""
    if len(state.worker_ids) <= 1:
        return
    lease_workers = {str(worker).strip() for worker, lease in state.worker_authority_leases if str(lease).strip()}
    missing = [worker for worker in state.worker_ids[1:] if worker not in lease_workers]
    if missing:
        raise RuntimeError(f"replica authority inheritance missing for worker: {missing[0]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    state_path = Path(args.state)
    output_path = Path(args.output)
    plan = load_plan(plan_path)
    state = load_state(state_path, plan)
    require_replica_lease = bool(plan.get("require_replica_authority_lease", True))

    if require_replica_lease:
        _assert_mandatory_replica_leases(state)

    replica_profile = select_replica_profile(
        parent_profile=state.authority_profile,
        allowed_profiles=plan["allowed_authority_profiles"],
        configured_profile=plan.get("replica_authority_profile"),
        mode=str(plan.get("replica_authority_mode") or "configured"),
    )
    if require_replica_lease and not replica_profile:
        raise RuntimeError("mandatory replica authority inheritance requires a pre-authorized profile")

    envelope = ProductionEvolutionEnvelope.create(
        allowed_authority_profiles=plan["allowed_authority_profiles"],
        allowed_deploy_targets=plan["allowed_deploy_targets"],
        replica_authority_profile=replica_profile,
        max_workers=int(plan.get("max_workers", 8)),
        max_replication_per_run=int(plan.get("max_replication_per_run", 1)),
        max_deploys_per_run=int(plan.get("max_deploys_per_run", 0)),
        max_deploys_per_day=int(plan.get("max_deploys_per_day", 0)),
        envelope_id=str(plan.get("envelope_id") or "production-evolution-auto-cycle-v1"),
    )

    requested_replicas = max(0, int(plan.get("requested_replicas_per_cycle", 1)))
    configured_targets = tuple(str(v) for v in plan.get("deploy_targets_per_cycle") or ())

    def tune_fn(current: EvolutionState) -> Mapping[str, Any]:
        return {
            "verified": True,
            "requested_replicas": requested_replicas,
            "requested_authority_profile": current.authority_profile,
            "deploy_targets": configured_targets,
            "artifact": {
                "generation": current.generation + 1,
                "cycle": "scheduled-production-evolution",
            },
        }

    def replicate_fn(parent_id: str, count: int):
        existing = set(state.worker_ids)
        produced: list[str] = []
        candidate = 1
        while len(produced) < count:
            worker_id = f"replica-g{state.generation + 1}-{candidate}"
            candidate += 1
            if worker_id not in existing:
                produced.append(worker_id)
        return produced

    def authority_fn(profile: str) -> Mapping[str, Any]:
        return {
            "approved": True,
            "profile": profile,
            "lease_id": f"authority-{_id(envelope.envelope_id, state.generation + 1, profile)}",
            "basis": "pre-authorized-production-envelope",
        }

    def replica_authority_fn(parent_id: str, child_id: str, profile: str) -> Mapping[str, Any]:
        if profile != replica_profile:
            raise RuntimeError("replica profile drifted from selected production profile")
        return issue_nondelegable_replica_lease(
            envelope_id=envelope.envelope_id,
            parent_worker=parent_id,
            child_worker=child_id,
            profile=profile,
        )

    def deploy_fn(target: str, artifact: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "deployed": False,
            "target": target,
            "reason": "no production deployment adapter configured for scheduled cycle",
        }

    persisted: dict[str, Any] = {}

    def persist_fn(checkpoint: Mapping[str, Any]) -> Mapping[str, Any]:
        checkpoint_id = f"checkpoint-{_id(envelope.envelope_id, checkpoint['run_id'], checkpoint['generation'])}"
        persisted.update(dict(checkpoint))
        persisted["checkpoint_id"] = checkpoint_id
        persisted["replica_authority_mode"] = str(plan.get("replica_authority_mode") or "configured")
        persisted["replica_authority_profile"] = replica_profile
        persisted["replica_authority_delegable"] = False
        persisted["require_replica_authority_lease"] = require_replica_lease
        return {"persisted": True, "checkpoint_id": checkpoint_id}

    result = ProductionEvolutionLoop(envelope).run(
        state,
        tune_fn=tune_fn,
        replicate_fn=replicate_fn,
        authority_fn=authority_fn,
        deploy_fn=deploy_fn,
        persist_fn=persist_fn,
        replica_authority_fn=replica_authority_fn,
    )

    if require_replica_lease:
        _assert_mandatory_replica_leases(
            EvolutionState(
                generation=result.generation,
                worker_ids=result.worker_ids,
                authority_profile=result.authority_profile,
                deploys_today=result.deploys_today,
                previous_checkpoint_id=result.checkpoint_id,
                worker_authority_leases=result.worker_authority_leases,
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, default=list) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_id": result.run_id,
        "generation": result.generation,
        "workers": result.worker_ids,
        "worker_authority_leases": result.worker_authority_leases,
        "authority_profile": result.authority_profile,
        "replica_authority_profile": replica_profile,
        "replica_authority_delegable": False,
        "require_replica_authority_lease": require_replica_lease,
        "checkpoint_id": result.checkpoint_id,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
