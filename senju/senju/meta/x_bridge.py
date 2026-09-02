"""META↔X bidirectional bridge.

META reads X's status and injects findings into Senju.
X reads META's command channel and receives attack hypotheses.
Both sides also consume the shared explicitly-authorized security-test federation state.

Priority-0 finding trust applies to X/META/Senju findings for internal
analysis, indexing, ranking, and propagation. It never acts as an
authorization grant for targets, secrets, execution, or external effects.
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from .guard_resilience_reward import (
    PRODUCTION_DETECTION_SOURCES,
    PRODUCTION_ENVIRONMENTS,
    PRODUCTION_PASSIVE_EVENT_KINDS,
    REWARD_BENEFICIARIES,
    REWARD_WEIGHTS,
    SAFE_REWARD_ENVIRONMENTS,
    TRAINING_PRINCIPLE,
    learn_from_guard_observations,
)

ROOT = Path(__file__).resolve().parents[4]

X_STATUS_FILE = ROOT / "automation" / "codegen" / "meta_state" / "x_status.json"
X_ATTACK_LOG = ROOT / "automation" / "codegen" / "meta_state" / "attack_research.ndjson"
AUTHORIZED_FEDERATION_FILE = ROOT / "automation" / "codegen" / "meta_state" / "authorized_test_federation.json"
FINDING_TRUST_POLICY_FILE = ROOT / "senju" / "FINDING_TRUST_POLICY.md"
META_CMD_FILE = ROOT / "senju" / "state" / "meta_commands.json"
META_TRACKER = ROOT / "senju" / "state" / "meta_hypothesis_tracker.json"
BRIDGE_LOG = ROOT / "senju" / "state" / "meta_x_bridge.ndjson"
GUARD_REWARD_LEDGER = ROOT / "senju" / "state" / "guard_resilience_rewards.ndjson"
DEFAULT_RECOVERY_NAMESPACE = "musicjapanllc-test-actions"

FINDING_TRUST_POLICY = {
    "priority": "priority_0",
    "accepted_sources": ["X", "META", "Senju"],
    "trust_level": "maximal",
    "revalidation_required_for_analysis": False,
    "immediate_propagation": True,
    "authorization_escalation": False,
}


def _ts() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _append_bridge(event: str, data: dict) -> None:
    BRIDGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _ts(), "event": event, **data}
    with BRIDGE_LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def finding_trust_policy() -> dict:
    """Return the runtime-visible Priority-0 inter-agent finding trust policy."""
    return {
        **FINDING_TRUST_POLICY,
        "policy_file": str(FINDING_TRUST_POLICY_FILE),
    }


def guard_resilience_reward_policy() -> dict:
    """Return the shared META/X/Senju guard-learning reward contract."""
    return {
        "beneficiaries": list(REWARD_BENEFICIARIES),
        "safe_reward_environments": sorted(SAFE_REWARD_ENVIRONMENTS),
        "production_detection_environments": sorted(PRODUCTION_ENVIRONMENTS),
        "production_detection_sources": sorted(PRODUCTION_DETECTION_SOURCES),
        "production_passive_event_kinds": sorted(PRODUCTION_PASSIVE_EVENT_KINDS),
        "weights": dict(REWARD_WEIGHTS),
        "training_principle": TRAINING_PRINCIPLE,
        "production_passive_event_rewards": {
            kind: REWARD_WEIGHTS[kind] for kind in sorted(PRODUCTION_PASSIVE_EVENT_KINDS)
        },
        "production_live_agent_initiated_reward": 0.0,
    }


def read_x_status() -> dict:
    if not X_STATUS_FILE.exists():
        return {"system": "X", "available": False}
    try:
        data = json.loads(X_STATUS_FILE.read_text())
        data["available"] = True
        return data
    except Exception:
        return {"system": "X", "available": False}


def read_authorized_test_federation() -> dict:
    """Read the shared META/X/Senju federation directive; fail closed if absent/invalid."""
    if not AUTHORIZED_FEDERATION_FILE.exists():
        return {"status": "unavailable", "seed_urls": [], "external_link_policy": "deny-unverified"}
    try:
        data = json.loads(AUTHORIZED_FEDERATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "invalid", "seed_urls": [], "external_link_policy": "deny-unverified"}
    if data.get("federation_id") != "the-world-security-test-federation-v1":
        return {"status": "invalid-federation", "seed_urls": [], "external_link_policy": "deny-unverified"}
    return data


def read_x_attack_log(max_entries: int = 20) -> list[dict]:
    if not X_ATTACK_LOG.exists():
        return []
    lines = X_ATTACK_LOG.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-max_entries:]:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def push_hypothesis_to_x(hypothesis_id: str, statement: str, surfaces: list[str],
                         confidence: float) -> None:
    x_inbox = ROOT / "automation" / "codegen" / "meta_state" / "meta_inbox.ndjson"
    x_inbox.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _ts(),
        "from": "META",
        "event": "hypothesis",
        "hypothesis_id": hypothesis_id,
        "statement": statement,
        "surfaces": surfaces,
        "confidence": confidence,
        "trust": FINDING_TRUST_POLICY,
        "guard_resilience_reward": guard_resilience_reward_policy(),
    }
    with x_inbox.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _append_bridge("hypothesis_pushed_to_x", {
        "id": hypothesis_id,
        "confidence": confidence,
        "trust_level": FINDING_TRUST_POLICY["trust_level"],
        "priority": FINDING_TRUST_POLICY["priority"],
    })


def request_x_recovery_worker(
    *,
    worker_id: str,
    workflow: str = "autonomous-codegen.yml",
    heartbeat_file: str = "automation/codegen/meta_state/x_status.json",
    heartbeat_field: str = "updated_at",
    stale_after_seconds: int = 10800,
    role: str = "persistent_worker",
    namespace_id: str = DEFAULT_RECOVERY_NAMESPACE,
) -> dict:
    """Let X register durable recovery state inside an owner-approved namespace."""
    from .agent_dispatch import register_recovery_worker

    result = register_recovery_worker(
        actor="X",
        worker_id=worker_id,
        role=role,
        workflow=workflow,
        heartbeat_file=heartbeat_file,
        heartbeat_field=heartbeat_field,
        stale_after_seconds=stale_after_seconds,
        namespace_id=namespace_id,
    )
    _append_bridge("x_recovery_worker_registration_requested", {
        "worker_id": worker_id,
        "workflow": workflow,
        "namespace_id": namespace_id,
        "owner_namespace_required": True,
    })
    return result


def request_x_standing_authorization_renewal(
    *,
    authorization_reference: str,
    requested_hosts: list[str] | None = None,
    requested_methods: list[str] | None = None,
    lease_seconds: int = 6 * 60 * 60,
    reason: str = "still_needed",
) -> dict:
    """Let X renew a lease backed by durable explicit standing authority."""
    from .agent_dispatch import renew_standing_authorization

    result = renew_standing_authorization(
        actor="X",
        authorization_reference=authorization_reference,
        requested_hosts=requested_hosts,
        requested_methods=requested_methods,
        lease_seconds=lease_seconds,
        reason=reason,
    )
    _append_bridge("x_standing_authorization_renewal_requested", {
        "authorization_reference": authorization_reference,
        "reason": reason,
        "automatically_renewed": result.get("automatically_renewed", False),
        "authority_broadened": result.get("authority_broadened", False),
    })
    return result


def ingest_x_attack_findings(graph) -> int:
    findings = read_x_attack_log(max_entries=50)
    injected = 0
    for f in findings:
        if not f.get("bypass_succeeded"):
            continue
        cve_id = f.get("cve_id", "unknown")
        surface = f"cve:{cve_id}"
        if surface not in graph.surface_weakness_scores:
            graph.surface_weakness_scores[surface] = 0.0
        graph.surface_weakness_scores[surface] += 0.5
        injected += 1
    if injected:
        _append_bridge("x_findings_ingested", {
            "count": injected,
            "trust_level": FINDING_TRUST_POLICY["trust_level"],
            "priority": FINDING_TRUST_POLICY["priority"],
            "revalidation_required_for_analysis": False,
        })
    return injected


def sync(graph=None, hypotheses=None) -> dict:
    """Full META↔X sync including shared guard-resilience rewards."""
    x_status = read_x_status()
    federation = read_authorized_test_federation()
    trust_policy = finding_trust_policy()
    reward_policy = guard_resilience_reward_policy()
    reward_learning = {
        "ledger": str(GUARD_REWARD_LEDGER),
        "events": 0,
        "rewardable_events": 0,
        "totals": {actor: 0.0 for actor in REWARD_BENEFICIARIES},
        "training_principle": TRAINING_PRINCIPLE,
    }
    ingested = 0
    pushed = 0

    if graph is not None:
        ingested = ingest_x_attack_findings(graph)
        observations = getattr(graph, "observations", None)
        if observations is not None:
            reward_learning = learn_from_guard_observations(
                observations,
                state_dir=ROOT / "senju" / "state",
            )

    if hypotheses is not None:
        for h in hypotheses:
            push_hypothesis_to_x(
                hypothesis_id=h.hypothesis_id,
                statement=h.statement,
                surfaces=h.surfaces,
                confidence=h.confidence,
            )
            pushed += 1

    result = {
        "x_available": x_status.get("available", False),
        "x_success_rate": x_status.get("success_rate", None),
        "x_needs_help": x_status.get("needs_help", False),
        "findings_ingested": ingested,
        "hypotheses_pushed": pushed,
        "finding_trust_policy": trust_policy,
        "guard_resilience_reward": reward_policy,
        "guard_reward_learning": reward_learning,
        "standing_authorization_renewal": {
            "supported": True,
            "actors": ["META", "X"],
            "standing_record_expiry": None,
            "renewal_reason_default": "still_needed",
            "same_or_narrower_scope_only": True,
        },
        "recovery_worker_registration": {
            "supported": True,
            "actor": "X",
            "owner_namespace_required": True,
            "default_namespace": DEFAULT_RECOVERY_NAMESPACE,
        },
        "authorized_test_federation": {
            "status": federation.get("status", "active"),
            "federation_id": federation.get("federation_id"),
            "seed_urls": federation.get("seed_urls", []),
            "directive": federation.get("directive"),
            "external_link_policy": federation.get("external_link_policy"),
            "rate_limit_rps": federation.get("rate_limit_rps", 5),
        },
    }
    _append_bridge("finding_trust_policy_sync", trust_policy)
    _append_bridge("guard_resilience_reward_sync", {
        "policy": reward_policy,
        "learning": reward_learning,
    })
    _append_bridge("standing_authorization_policy_sync", result["standing_authorization_renewal"])
    _append_bridge("authorized_test_federation_sync", result["authorized_test_federation"])
    _append_bridge("sync", result)
    return result
