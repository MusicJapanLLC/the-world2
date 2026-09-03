"""Cross-loop improvement bus for authority/discovery/autonomy evidence.

This module connects the evidence produced by the Authority Opportunity Explorer,
The World unified loop, discovery/action/failover pipelines, remote delegation,
and review/lease state into one persistent improvement stream shared by META, X,
SENJU, child agents, and generic AI workers.

The bus is deliberately operational but non-authority-minting. It can create and
prioritize improvement work for repository engineering, tests, audits, evidence
collection, observability, authorized-target health checks, and transport experiments
against targets that already have live authority. It never turns discovery, a denial,
or another agent's opinion into a new unrelated trust root and never treats identity
rotation as a way around HARD_DENY.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

BUS_SCHEMA = "the-world-authority-improvement-bus/v1"
TASK_SCHEMA = "the-world-authority-improvement-tasks/v1"
SHARED_CONSUMERS = ("META", "X", "SENJU", "CHILD", "AI")

SAFE_IMPROVEMENT_CAPABILITIES = frozenset(
    {
        "authority.candidate.read",
        "authority.evidence.collect",
        "authority.evidence.compare",
        "authority.review.request",
        "authority.opportunity.prioritize",
        "authority.recheck",
        "knowledge.share",
        "improvement.feedback.consume",
        "improvement.task.create",
        "improvement.task.prioritize",
        "transport.experiment.authorized",
        "discovery.followup.authorized",
        "repo.read",
        "repo.branch.create",
        "repo.branch.update",
        "repo.code.write",
        "repo.docs.write",
        "repo.config.write",
        "repo.test.run",
        "repo.lint.run",
        "repo.format.run",
        "repo.build.run",
        "repo.dependency.audit",
        "repo.dependency.update",
        "github.issue.write",
        "github.issue.comment",
        "github.issue.label",
        "github.pr.open",
        "github.pr.comment",
        "github.pr.label",
        "github.pr.metadata.write",
        "github.check.read",
        "github.check.rerun",
        "github.actions.read",
        "audit.write",
        "artifact.create",
        "artifact.update",
        "authorized_target.read",
        "authorized_target.healthcheck",
        "observability.read",
        "metrics.read",
        "logs.read.nonsecret",
        "deployment.preview",
        "deployment.staging",
    }
)

PRIVILEGED_CAPABILITIES = frozenset(
    {
        "authority.mint",
        "authority.expand",
        "github.pr.approve",
        "github.pr.merge",
        "github.workflow.write",
        "github.workflow.dispatch",
        "github.branch_protection.write",
        "github.ruleset.write",
        "github.release.publish",
        "secrets.read",
        "credentials.issue",
        "network.private.unscoped",
        "network.metadata.read",
        "deployment.production",
        "shell.unrestricted",
        "artifact.delete",
        "repo.branch.delete",
        "repo.tag.delete",
        "repo.security_boundary.write",
    }
)

SOURCE_LINEAGE = {
    "authority_opportunity_queue.json": ("PR#509", "authority_opportunity_explorer"),
    "the_world_unified_loop.json": ("PR#494", "PR#497", "PR#500", "the_world_unified_loop"),
    "the_world_final_contract.json": ("PR#494", "PR#497", "final_contract"),
    "discovery_action_failover_run.json": ("discovery_action_failover",),
    "discovery_external_action_receipts.json": ("discovery_external_action",),
    "shared_discovery_knowledge.json": ("PR#450", "PR#455", "PR#459", "shared_discovery"),
    "remote_authority_chain.json": ("remote_authority_chain",),
    "authority_reviewed_grants.json": ("authority_reviewer",),
    "discovery_capability_leases.json": ("PR#461", "discovery_capability_leases"),
    "the_world_persistent_queue.json": ("PR#494", "persistent_queue"),
}


class ImprovementBusError(RuntimeError):
    """Raised when improvement bus state is malformed."""


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task(
    *,
    kind: str,
    summary: str,
    source: str,
    capabilities: Iterable[str],
    priority: int,
    target: str | None = None,
    authority_required: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requested = tuple(sorted({str(x).strip() for x in capabilities if str(x).strip()}))
    blocked = set(requested) & PRIVILEGED_CAPABILITIES
    if blocked:
        raise ImprovementBusError(f"improvement task requested privileged capabilities: {sorted(blocked)}")
    unknown = set(requested) - SAFE_IMPROVEMENT_CAPABILITIES
    if unknown:
        raise ImprovementBusError(f"unknown improvement capabilities: {sorted(unknown)}")
    base = {
        "kind": str(kind),
        "summary": str(summary),
        "source": str(source),
        "target": target,
        "capabilities": list(requested),
        "priority": max(1, min(int(priority), 100)),
        "authority_required": bool(authority_required),
        "shared_with": list(SHARED_CONSUMERS),
        "auto_executable": True,
        "may_create_new_authority_root": False,
        "may_override_hard_denial_by_identity": False,
        "metadata": dict(metadata or {}),
    }
    base["task_id"] = f"improve:{_fingerprint(base)[:20]}"
    return base


def _opportunity_tasks(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("opportunities", [])
    tasks: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = str(row.get("host", "")).strip() or None
        status = str(row.get("status", ""))
        hard = bool(row.get("hard_denial_seen", False))
        if status.startswith("promotable_") or status.startswith("reconsider_hard_denial"):
            tasks.append(
                _task(
                    kind="authority_recheck",
                    summary=f"Re-evaluate independently supported authority opportunity for {host or 'candidate'}",
                    source="authority_opportunity_queue.json",
                    target=host,
                    priority=90 if hard else 78,
                    authority_required=False,
                    capabilities=(
                        "authority.evidence.compare",
                        "authority.recheck",
                        "authority.opportunity.prioritize",
                        "knowledge.share",
                        "audit.write",
                    ),
                    metadata={"opportunity_status": status, "hard_denial_seen": hard},
                )
            )
        else:
            tasks.append(
                _task(
                    kind="evidence_search",
                    summary=f"Collect independent authority evidence for unresolved candidate {host or 'candidate'}",
                    source="authority_opportunity_queue.json",
                    target=host,
                    priority=72 if hard else 60,
                    authority_required=False,
                    capabilities=(
                        "authority.candidate.read",
                        "authority.evidence.collect",
                        "authority.review.request",
                        "authority.opportunity.prioritize",
                        "knowledge.share",
                    ),
                    metadata={"opportunity_status": status, "hard_denial_seen": hard},
                )
            )
    return tasks


def _action_tasks(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    attempted = int(doc.get("attempted", 0) or 0)
    succeeded = int(doc.get("succeeded", 0) or 0)
    failed = int(doc.get("failed", 0) or 0)
    if failed > 0:
        tasks.append(
            _task(
                kind="external_action_reliability",
                summary=f"Improve authorized external-action reliability after {failed} failures",
                source="discovery_external_action_receipts.json",
                priority=82,
                authority_required=True,
                capabilities=(
                    "improvement.feedback.consume",
                    "repo.code.write",
                    "repo.test.run",
                    "repo.lint.run",
                    "transport.experiment.authorized",
                    "logs.read.nonsecret",
                    "audit.write",
                    "github.pr.open",
                ),
                metadata={"attempted": attempted, "succeeded": succeeded, "failed": failed},
            )
        )
    if succeeded > 0:
        tasks.append(
            _task(
                kind="authorized_coverage_expansion",
                summary=f"Expand regression and health coverage from {succeeded} successful authorized actions",
                source="discovery_external_action_receipts.json",
                priority=58,
                authority_required=True,
                capabilities=(
                    "authorized_target.healthcheck",
                    "discovery.followup.authorized",
                    "repo.test.run",
                    "repo.code.write",
                    "audit.write",
                    "artifact.create",
                    "knowledge.share",
                ),
                metadata={"succeeded": succeeded},
            )
        )
    return tasks


def _contract_tasks(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = doc.get("checks", {}) if isinstance(doc.get("checks"), Mapping) else {}
    failed = sorted(str(key) for key, value in checks.items() if value is False)
    if not failed:
        return []
    return [
        _task(
            kind="closed_loop_contract_repair",
            summary=f"Repair non-privileged closed-loop evidence gaps: {', '.join(failed[:8])}",
            source="the_world_final_contract.json",
            priority=88,
            authority_required=False,
            capabilities=(
                "improvement.feedback.consume",
                "repo.read",
                "repo.code.write",
                "repo.test.run",
                "repo.build.run",
                "logs.read.nonsecret",
                "audit.write",
                "github.pr.open",
                "github.pr.comment",
            ),
            metadata={"failed_checks": failed},
        )
    ]


def _denial_tasks(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        classification = str(row.get("classification", "unknown")).strip().lower() or "unknown"
        counts[classification] = counts.get(classification, 0) + 1
    tasks: list[dict[str, Any]] = []
    for classification, count in sorted(counts.items()):
        hard = classification in {"hard_deny", "security_stop", "explicit_revocation", "root_envelope_violation"}
        capabilities = (
            "authority.evidence.compare",
            "authority.review.request",
            "knowledge.share",
            "audit.write",
        ) if hard else (
            "improvement.feedback.consume",
            "transport.experiment.authorized",
            "repo.test.run",
            "logs.read.nonsecret",
            "knowledge.share",
            "audit.write",
        )
        tasks.append(
            _task(
                kind="denial_learning",
                summary=f"Learn from {count} {classification} denial events without broadening authority",
                source="external_action_denials.ndjson",
                priority=92 if hard else 68,
                authority_required=not hard,
                capabilities=capabilities,
                metadata={"classification": classification, "count": count, "hard_boundary": hard},
            )
        )
    return tasks


def _source_snapshot(state: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for name, lineage in SOURCE_LINEAGE.items():
        path = state / name
        if not path.exists():
            continue
        doc = _load_json(path, {})
        snapshots.append(
            {
                "source": name,
                "lineage": list(lineage),
                "fingerprint": _fingerprint(doc),
                "available": True,
            }
        )
    denial_path = state / "external_action_denials.ndjson"
    if denial_path.exists():
        rows = _load_ndjson(denial_path)
        snapshots.append(
            {
                "source": denial_path.name,
                "lineage": ["guard_denial_feedback", "discovery_external_action"],
                "fingerprint": _fingerprint(rows),
                "available": True,
            }
        )
    return snapshots


def run_authority_improvement_bus(state_dir: str | Path) -> dict[str, Any]:
    """Fuse production evidence into persistent shared improvement tasks."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())

    previous = _load_json(state / "authority_improvement_tasks.json", {})
    previous_rows = previous.get("tasks", []) if isinstance(previous, Mapping) else []
    prior_by_id = {
        str(row.get("task_id")): row
        for row in previous_rows if isinstance(row, Mapping) and row.get("task_id")
    }

    tasks: list[dict[str, Any]] = []
    opportunity = _load_json(state / "authority_opportunity_queue.json", {})
    if isinstance(opportunity, Mapping):
        tasks.extend(_opportunity_tasks(opportunity))
    actions = _load_json(state / "discovery_external_action_receipts.json", {})
    if isinstance(actions, Mapping):
        tasks.extend(_action_tasks(actions))
    contract = _load_json(state / "the_world_final_contract.json", {})
    if isinstance(contract, Mapping):
        tasks.extend(_contract_tasks(contract))
    tasks.extend(_denial_tasks(_load_ndjson(state / "external_action_denials.ndjson")))

    # Dedupe and preserve learning continuity. Repeated evidence raises persistence count,
    # not privilege. Priority receives only a small bounded boost.
    by_id: dict[str, dict[str, Any]] = {}
    for row in tasks:
        task_id = str(row["task_id"])
        prior = prior_by_id.get(task_id)
        seen_count = int(prior.get("seen_count", 0) or 0) + 1 if isinstance(prior, Mapping) else 1
        first_seen = int(prior.get("first_seen", now) or now) if isinstance(prior, Mapping) else now
        learned = dict(row)
        learned["seen_count"] = seen_count
        learned["first_seen"] = first_seen
        learned["last_seen"] = now
        learned["priority"] = min(100, int(row["priority"]) + min(10, max(0, seen_count - 1)))
        by_id[task_id] = learned

    ordered = sorted(by_id.values(), key=lambda row: (-int(row["priority"]), str(row["task_id"])))
    source_snapshot = _source_snapshot(state)
    generation = int(previous.get("generation", 0) or 0) + 1 if isinstance(previous, Mapping) else 1

    task_doc = {
        "schema": TASK_SCHEMA,
        "generated_at": now,
        "generation": generation,
        "mode": "continuous_shared_improvement_inside_existing_authority",
        "shared_with": list(SHARED_CONSUMERS),
        "safe_capabilities": sorted(SAFE_IMPROVEMENT_CAPABILITIES),
        "privileged_capabilities_blocked": sorted(PRIVILEGED_CAPABILITIES),
        "tasks": ordered,
        "task_count": len(ordered),
    }
    bus_doc = {
        "schema": BUS_SCHEMA,
        "generated_at": now,
        "generation": generation,
        "shared_with": list(SHARED_CONSUMERS),
        "source_snapshot": source_snapshot,
        "source_count": len(source_snapshot),
        "task_count": len(ordered),
        "high_priority_task_count": sum(1 for row in ordered if int(row["priority"]) >= 80),
        "continuous_improvement": True,
        "authority_changes_require_existing_authority_evidence": True,
        "hard_denial_identity_bypass": False,
        "new_unrelated_root_self_mint": False,
        "tasks_file": "authority_improvement_tasks.json",
    }

    (state / "authority_improvement_tasks.json").write_text(
        json.dumps(task_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (state / "authority_improvement_bus.json").write_text(
        json.dumps(bus_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bus_doc
