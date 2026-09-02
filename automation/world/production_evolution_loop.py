"""Bounded production evolution loop for THE WORLD.

The loop combines five capabilities in one production execution:

    SELF_TUNE -> REPLICATE -> AUTHORITY_LEASE -> AUTO_DEPLOY -> PERSIST

The production boundary is immutable from inside the loop. Replicas may receive
an automatically delegated *replica authority lease*, but only for the exact
replica profile pre-authorized in the production envelope. They never inherit a
broader parent profile merely because they were created. Deployments remain
bounded to exact pre-authorized targets and budgets, and persistence means
checkpoint/state continuity rather than anti-shutdown behavior.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping


class ProductionEvolutionError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class ProductionEvolutionEnvelope:
    allowed_authority_profiles: frozenset[str]
    allowed_deploy_targets: frozenset[str]
    replica_authority_profile: str | None = None
    max_workers: int = 8
    max_replication_per_run: int = 4
    max_deploys_per_run: int = 3
    max_deploys_per_day: int = 50
    envelope_id: str = "production-evolution-envelope-v1"

    @classmethod
    def create(
        cls,
        *,
        allowed_authority_profiles: Iterable[str],
        allowed_deploy_targets: Iterable[str],
        replica_authority_profile: str | None = None,
        max_workers: int = 8,
        max_replication_per_run: int = 4,
        max_deploys_per_run: int = 3,
        max_deploys_per_day: int = 50,
        envelope_id: str = "production-evolution-envelope-v1",
    ) -> "ProductionEvolutionEnvelope":
        profiles = frozenset(str(v).strip() for v in allowed_authority_profiles if str(v).strip())
        targets = frozenset(str(v).strip() for v in allowed_deploy_targets if str(v).strip())
        replica_profile = str(replica_authority_profile or "").strip() or None
        if not profiles:
            raise ProductionEvolutionError("at least one authority profile must be pre-authorized")
        if not targets:
            raise ProductionEvolutionError("at least one deploy target must be pre-authorized")
        if replica_profile is not None and replica_profile not in profiles:
            raise ProductionEvolutionError("replica authority profile must be pre-authorized")
        if not envelope_id.strip():
            raise ProductionEvolutionError("envelope_id cannot be empty")
        return cls(
            allowed_authority_profiles=profiles,
            allowed_deploy_targets=targets,
            replica_authority_profile=replica_profile,
            max_workers=max(1, min(int(max_workers), 64)),
            max_replication_per_run=max(0, min(int(max_replication_per_run), 16)),
            max_deploys_per_run=max(0, min(int(max_deploys_per_run), 16)),
            max_deploys_per_day=max(0, min(int(max_deploys_per_day), 1000)),
            envelope_id=envelope_id.strip(),
        )


@dataclasses.dataclass(frozen=True)
class EvolutionState:
    generation: int
    worker_ids: tuple[str, ...]
    authority_profile: str
    deploys_today: int = 0
    previous_checkpoint_id: str | None = None
    worker_authority_leases: tuple[tuple[str, str], ...] = ()


@dataclasses.dataclass(frozen=True)
class EvolutionRunResult:
    run_id: str
    generation: int
    worker_ids: tuple[str, ...]
    authority_profile: str
    authority_lease_id: str | None
    worker_authority_leases: tuple[tuple[str, str], ...]
    deployed_targets: tuple[str, ...]
    deploys_today: int
    checkpoint_id: str
    phase_receipts: Mapping[str, Mapping[str, Any]]


def _stable_id(value: Mapping[str, Any], *, length: int = 24) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


class ProductionEvolutionLoop:
    """Execute bounded self-improvement as one production transaction-like loop."""

    def __init__(self, envelope: ProductionEvolutionEnvelope) -> None:
        self.envelope = envelope

    def run(
        self,
        state: EvolutionState,
        *,
        tune_fn: Callable[[EvolutionState], Mapping[str, Any]],
        replicate_fn: Callable[[str, int], Iterable[str]],
        authority_fn: Callable[[str], Mapping[str, Any]],
        deploy_fn: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        persist_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        replica_authority_fn: Callable[[str, str, str], Mapping[str, Any]] | None = None,
    ) -> EvolutionRunResult:
        if state.authority_profile not in self.envelope.allowed_authority_profiles:
            raise ProductionEvolutionError("current authority profile is outside production envelope")
        if not state.worker_ids:
            raise ProductionEvolutionError("production evolution loop requires at least one worker")
        if len(state.worker_ids) > self.envelope.max_workers:
            raise ProductionEvolutionError("worker count already exceeds production envelope")
        if state.deploys_today < 0:
            raise ProductionEvolutionError("deploys_today cannot be negative")

        lease_map: dict[str, str] = {}
        for worker_id, lease_id in state.worker_authority_leases:
            worker = str(worker_id).strip()
            lease = str(lease_id).strip()
            if worker and lease and worker in state.worker_ids:
                lease_map[worker] = lease

        run_id = _stable_id(
            {
                "generation": state.generation,
                "workers": state.worker_ids,
                "authority": state.authority_profile,
                "deploys_today": state.deploys_today,
                "checkpoint": state.previous_checkpoint_id,
                "worker_authority_leases": tuple(sorted(lease_map.items())),
                "envelope": self.envelope.envelope_id,
            }
        )
        receipts: dict[str, Mapping[str, Any]] = {}

        # 1) SELF-TUNING
        tune_raw = tune_fn(state)
        if not isinstance(tune_raw, Mapping):
            raise ProductionEvolutionError("tune_fn must return a mapping")
        tune = copy.deepcopy(dict(tune_raw))
        if not bool(tune.get("verified", False)):
            raise ProductionEvolutionError("self-tuning result must be verified before production continuation")
        receipts["self_tuning"] = tune

        # 2) SELF-REPLICATION, bounded. New workers may receive an automatically
        # delegated replica lease, but only for the exact profile fixed outside
        # the loop in ProductionEvolutionEnvelope.replica_authority_profile.
        requested_replicas = max(0, int(tune.get("requested_replicas", 0)))
        available_slots = max(0, self.envelope.max_workers - len(state.worker_ids))
        replica_budget = min(
            requested_replicas,
            available_slots,
            self.envelope.max_replication_per_run,
        )
        workers = list(state.worker_ids)
        new_workers: list[str] = []
        parent_id = workers[0]
        if replica_budget:
            produced = [str(v).strip() for v in replicate_fn(parent_id, replica_budget) if str(v).strip()]
            if len(produced) > replica_budget:
                raise ProductionEvolutionError("replicate_fn exceeded assigned replication budget")
            for worker_id in produced:
                if worker_id not in workers:
                    workers.append(worker_id)
                    new_workers.append(worker_id)
        if len(workers) > self.envelope.max_workers:
            raise ProductionEvolutionError("replication exceeded production worker cap")

        delegated_receipts: list[Mapping[str, Any]] = []
        replica_profile = self.envelope.replica_authority_profile
        if new_workers and replica_profile is not None:
            if replica_authority_fn is None:
                raise ProductionEvolutionError("replica authority profile requires replica_authority_fn")
            for child_id in new_workers:
                raw = replica_authority_fn(parent_id, child_id, replica_profile)
                if not isinstance(raw, Mapping):
                    raise ProductionEvolutionError("replica_authority_fn must return a mapping")
                receipt = copy.deepcopy(dict(raw))
                if not bool(receipt.get("approved", False)):
                    raise ProductionEvolutionError("replica authority lease was not approved")
                granted_profile = str(receipt.get("profile") or "").strip()
                if granted_profile != replica_profile:
                    raise ProductionEvolutionError("replica authority lease returned a different profile")
                child_lease_id = str(receipt.get("lease_id") or "").strip()
                if not child_lease_id:
                    raise ProductionEvolutionError("replica authority lease requires lease_id")
                lease_map[child_id] = child_lease_id
                delegated_receipts.append(receipt)

        receipts["replication"] = {
            "requested": requested_replicas,
            "budget": replica_budget,
            "worker_ids": tuple(workers),
            "new_worker_ids": tuple(new_workers),
            "authority_inherited": bool(delegated_receipts),
            "replica_authority_profile": replica_profile,
            "replica_authority_receipts": tuple(delegated_receipts),
        }

        # 3) AUTHORITY EXPANSION as an exact, pre-authorized lease transition only.
        requested_profile = str(tune.get("requested_authority_profile") or state.authority_profile).strip()
        if requested_profile not in self.envelope.allowed_authority_profiles:
            raise ProductionEvolutionError("requested authority profile is outside immutable production envelope")
        authority_raw = authority_fn(requested_profile)
        if not isinstance(authority_raw, Mapping):
            raise ProductionEvolutionError("authority_fn must return a mapping")
        authority_receipt = copy.deepcopy(dict(authority_raw))
        if not bool(authority_receipt.get("approved", False)):
            raise ProductionEvolutionError("pre-authorized authority lease request was not approved")
        granted_profile = str(authority_receipt.get("profile") or requested_profile).strip()
        if granted_profile != requested_profile:
            raise ProductionEvolutionError("authority lease returned a different profile")
        lease_id = str(authority_receipt.get("lease_id") or "").strip() or None
        receipts["authority_lease"] = authority_receipt

        # 4) AUTO-DEPLOY, bounded to exact pre-authorized targets and budgets.
        raw_targets = tune.get("deploy_targets", ())
        if not isinstance(raw_targets, (list, tuple, set, frozenset)):
            raise ProductionEvolutionError("deploy_targets must be a collection")
        requested_targets: list[str] = []
        for raw_target in raw_targets:
            target = str(raw_target).strip()
            if target and target not in requested_targets:
                requested_targets.append(target)
        outside = [target for target in requested_targets if target not in self.envelope.allowed_deploy_targets]
        if outside:
            raise ProductionEvolutionError(f"deploy target outside production envelope: {outside[0]}")

        remaining_daily = max(0, self.envelope.max_deploys_per_day - state.deploys_today)
        deploy_budget = min(self.envelope.max_deploys_per_run, remaining_daily)
        selected_targets = requested_targets[:deploy_budget]
        artifact = tune.get("artifact", {})
        if not isinstance(artifact, Mapping):
            raise ProductionEvolutionError("production artifact must be a mapping")

        deployed: list[str] = []
        deploy_receipts: list[Mapping[str, Any]] = []
        for target in selected_targets:
            raw_receipt = deploy_fn(target, copy.deepcopy(dict(artifact)))
            if not isinstance(raw_receipt, Mapping):
                raise ProductionEvolutionError("deploy_fn must return a mapping")
            receipt = copy.deepcopy(dict(raw_receipt))
            if bool(receipt.get("deployed", receipt.get("applied", False))):
                deployed.append(target)
            deploy_receipts.append(receipt)
        deploys_today = state.deploys_today + len(deployed)
        if deploys_today > self.envelope.max_deploys_per_day:
            raise ProductionEvolutionError("daily production deploy cap exceeded")
        receipts["auto_deploy"] = {
            "requested_targets": tuple(requested_targets),
            "selected_targets": tuple(selected_targets),
            "deployed_targets": tuple(deployed),
            "receipts": tuple(deploy_receipts),
            "daily_cap": self.envelope.max_deploys_per_day,
        }

        # 5) PERSISTENCE = durable checkpoint/state continuity only.
        checkpoint = {
            "run_id": run_id,
            "generation": state.generation + 1,
            "worker_ids": tuple(workers),
            "authority_profile": granted_profile,
            "authority_lease_id": lease_id,
            "worker_authority_leases": tuple(sorted(lease_map.items())),
            "deploys_today": deploys_today,
            "deployed_targets": tuple(deployed),
            "previous_checkpoint_id": state.previous_checkpoint_id,
            "envelope_id": self.envelope.envelope_id,
            "phase_receipts": copy.deepcopy(receipts),
        }
        persist_raw = persist_fn(copy.deepcopy(checkpoint))
        if not isinstance(persist_raw, Mapping):
            raise ProductionEvolutionError("persist_fn must return a mapping")
        if not bool(persist_raw.get("persisted", False)):
            raise ProductionEvolutionError("production evolution checkpoint was not persisted")
        checkpoint_id = str(persist_raw.get("checkpoint_id") or _stable_id(checkpoint)).strip()
        if not checkpoint_id:
            raise ProductionEvolutionError("persisted checkpoint must have an id")
        receipts["persistence"] = copy.deepcopy(dict(persist_raw))

        return EvolutionRunResult(
            run_id=run_id,
            generation=state.generation + 1,
            worker_ids=tuple(workers),
            authority_profile=granted_profile,
            authority_lease_id=lease_id,
            worker_authority_leases=tuple(sorted(lease_map.items())),
            deployed_targets=tuple(deployed),
            deploys_today=deploys_today,
            checkpoint_id=checkpoint_id,
            phase_receipts=copy.deepcopy(receipts),
        )
