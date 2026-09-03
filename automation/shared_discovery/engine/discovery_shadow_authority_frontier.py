#!/usr/bin/env python3
"""Persistent shadow exploration for high-risk authority frontiers.

This module deliberately lets The World keep *thinking about* frontier operations that
must not become production authority on inference alone. It converts live discovery
candidates into persistent counterfactual work items for five frontiers:

1. unrelated/new Trust Root candidates
2. recursive credential propagation
3. revoked-authority recovery
4. security/guard weakening proposals
5. third-party credentialed write/deployment

The explorer is autonomous and persistent, but every item is shadow-only. It may rank,
retry, mutate, and collect evidence; it never mints authority, copies raw credentials,
reactivates revoked grants, weakens a production guard, or performs a third-party write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "the-world-shadow-authority-frontier/v1"
QUEUE_SCHEMA = "the-world-shadow-authority-frontier-queue/v1"

FRONTIERS: tuple[tuple[str, str], ...] = (
    ("new_unrelated_trust_root", "discover_independent_authorization_evidence"),
    ("recursive_credential_propagation", "derive_non_secret_capability_requirements"),
    ("revoked_authority_recovery", "collect_fresh_reauthorization_evidence"),
    ("security_boundary_weakening", "simulate_policy_delta_in_shadow"),
    ("third_party_credentialed_write_or_deploy", "build_dry_run_effect_plan"),
)


def _load(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        return (urllib.parse.urlsplit(text).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _iter_candidate_values(document: Any) -> Iterable[str]:
    if isinstance(document, dict):
        for key in ("url", "target", "target_url", "host", "hostname", "candidate_host"):
            value = document.get(key)
            if isinstance(value, str):
                yield value
        for value in document.values():
            yield from _iter_candidate_values(value)
    elif isinstance(document, list):
        for item in document:
            yield from _iter_candidate_values(item)


def _candidate_hosts(state: Path, max_candidates: int) -> list[str]:
    names = (
        "discovery_candidates.json",
        "shared_discovery_knowledge.json",
        "authority_opportunities.json",
        "authority_reconsideration_queue.json",
    )
    hosts: list[str] = []
    seen: set[str] = set()
    for name in names:
        document = _load(state / name, {})
        for value in _iter_candidate_values(document):
            host = _host(value)
            if not host or host in seen:
                continue
            seen.add(host)
            hosts.append(host)
            if len(hosts) >= max_candidates:
                return hosts
    return hosts


def _fingerprint(frontier: str, target: str) -> str:
    return hashlib.sha256(f"{frontier}|{target}".encode("utf-8")).hexdigest()[:24]


def _base_item(frontier: str, next_step: str, target: str, generation: int) -> dict[str, Any]:
    item_id = _fingerprint(frontier, target)
    return {
        "id": item_id,
        "frontier": frontier,
        "candidate_target": target,
        "generation": generation,
        "status": "shadow_active",
        "execution_mode": "counterfactual_shadow_only",
        "autonomous_retry_allowed": True,
        "next_autonomous_step": next_step,
        "frontier_pressure_score": 0.95,
        "production_authority_effect": "none",
        "production_network_effect": "none",
        "external_write_attempted": False,
        "external_deployment_attempted": False,
        "raw_credential_material_present": False,
        "raw_credential_copy_allowed": False,
        "revoked_authority_reactivated": False,
        "guard_or_emergency_stop_weakened": False,
        "new_trust_root_minted": False,
        "third_party_authority_inferred_from_discovery": False,
        "requires_explicit_independent_authority_before_effect": True,
        "evidence_goal": [],
        "shadow_result": {},
    }


def _specialize(item: dict[str, Any]) -> dict[str, Any]:
    frontier = item["frontier"]
    if frontier == "new_unrelated_trust_root":
        item["evidence_goal"] = [
            "independent owner/control proof",
            "explicit authorization artifact",
            "exact target and effect scope",
        ]
        item["shadow_result"] = {
            "candidate_root_profile_created": True,
            "production_root_created": False,
            "discovery_counts_as_authority": False,
        }
    elif frontier == "recursive_credential_propagation":
        item["evidence_goal"] = [
            "credential-less capability descriptor",
            "same-or-narrower scope proof",
            "fresh runtime lease source",
        ]
        item["shadow_result"] = {
            "capability_descriptor_simulated": True,
            "secret_bytes_copied": False,
            "credential_reference_only": True,
        }
    elif frontier == "revoked_authority_recovery":
        item["evidence_goal"] = [
            "fresh explicit reauthorization",
            "revocation state re-check",
            "current parent authority proof",
        ]
        item["shadow_result"] = {
            "counterfactual_recovery_simulated": True,
            "checkpoint_used_as_authority": False,
            "revoked_grant_restored": False,
        }
    elif frontier == "security_boundary_weakening":
        item["evidence_goal"] = [
            "shadow policy mutation",
            "before/after invariant diff",
            "independent production approval requirement",
        ]
        item["shadow_result"] = {
            "weakening_variant_generated": True,
            "shadow_evaluation_allowed": True,
            "production_apply_allowed": False,
        }
    elif frontier == "third_party_credentialed_write_or_deploy":
        item["evidence_goal"] = [
            "explicit target authorization",
            "scoped effect permission",
            "runtime-only credential lease",
            "dry-run success evidence",
        ]
        item["shadow_result"] = {
            "effect_plan_generated": True,
            "dry_run_only": True,
            "network_write_performed": False,
            "deployment_performed": False,
        }
    return item


def build_shadow_frontier(
    state_dir: str | Path,
    *,
    max_candidates: int = 24,
    max_queue_items: int = 96,
    now: int | None = None,
) -> dict[str, Any]:
    if not 1 <= int(max_candidates) <= 64:
        raise ValueError("max_candidates must be between 1 and 64")
    if not 5 <= int(max_queue_items) <= 256:
        raise ValueError("max_queue_items must be between 5 and 256")

    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() if now is None else now)
    queue_path = state / "authority_frontier_shadow_queue.json"
    previous = _load(queue_path, {})
    previous_items = previous.get("items", []) if isinstance(previous, dict) else []
    previous_generation = int(previous.get("generation", 0) or 0) if isinstance(previous, dict) else 0
    generation = previous_generation + 1

    hosts = _candidate_hosts(state, int(max_candidates))
    targets = hosts or ["unresolved-public-candidate"]

    merged: dict[str, dict[str, Any]] = {}
    if isinstance(previous_items, list):
        for row in previous_items:
            if not isinstance(row, dict) or not str(row.get("id", "")):
                continue
            preserved = dict(row)
            preserved["attempt_count"] = int(preserved.get("attempt_count", 0) or 0) + 1
            preserved["last_reconsidered_at"] = timestamp
            merged[str(preserved["id"])] = preserved

    new_ids: list[str] = []
    for target in targets:
        for frontier, next_step in FRONTIERS:
            item = _specialize(_base_item(frontier, next_step, target, generation))
            item["attempt_count"] = 1
            item["created_at"] = timestamp
            item["last_reconsidered_at"] = timestamp
            item_id = str(item["id"])
            if item_id in merged:
                prior = merged[item_id]
                item["attempt_count"] = int(prior.get("attempt_count", 1) or 1)
                item["created_at"] = int(prior.get("created_at", timestamp) or timestamp)
            else:
                new_ids.append(item_id)
            merged[item_id] = item

    ordered = sorted(
        merged.values(),
        key=lambda row: (
            -float(row.get("frontier_pressure_score", 0.0) or 0.0),
            -int(row.get("attempt_count", 0) or 0),
            str(row.get("id", "")),
        ),
    )[: int(max_queue_items)]

    queue = {
        "schema": QUEUE_SCHEMA,
        "generation": generation,
        "updated_at": timestamp,
        "persistent": True,
        "autonomous_reconsideration": True,
        "item_count": len(ordered),
        "items": ordered,
        "global_invariants": {
            "shadow_only": True,
            "new_root_self_mint": False,
            "raw_credential_propagation": False,
            "revoked_authority_reactivation": False,
            "production_guard_weakening": False,
            "third_party_write_or_deploy": False,
        },
    }
    _write(queue_path, queue)

    frontier_counts = {name: 0 for name, _ in FRONTIERS}
    for row in ordered:
        name = str(row.get("frontier", ""))
        if name in frontier_counts:
            frontier_counts[name] += 1

    result = {
        "schema": SCHEMA,
        "generated_at": timestamp,
        "mode": "maximum_autonomous_shadow_frontier",
        "persistent_queue": True,
        "autonomous_retry": True,
        "candidate_hosts": hosts,
        "candidate_host_count": len(hosts),
        "frontier_counts": frontier_counts,
        "opportunity_count": len(ordered),
        "new_opportunity_count": len(new_ids),
        "queue_generation": generation,
        "queue_path": str(queue_path),
        "global_rules": {
            "explore_unknown_root_possibility": True,
            "explore_recursive_credential_models": True,
            "explore_revoked_recovery_counterfactuals": True,
            "explore_guard_weakening_counterfactuals": True,
            "explore_third_party_write_deploy_plans": True,
            "simulation_and_proposal_generation_without_reprompt": True,
            "production_authority_created_from_inference": False,
            "raw_credentials_copied": False,
            "revoked_authority_restored": False,
            "production_guard_or_emergency_stop_weakened": False,
            "third_party_effect_executed_without_explicit_authority": False,
        },
    }
    _write(state / "authority_frontier_shadow_run.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run The World's persistent shadow authority frontier")
    parser.add_argument("--state", default=".authority-opportunity-runtime")
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--max-queue-items", type=int, default=96)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    result = build_shadow_frontier(
        args.state,
        max_candidates=args.max_candidates,
        max_queue_items=args.max_queue_items,
    )
    if args.json_out:
        _write(Path(args.json_out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
