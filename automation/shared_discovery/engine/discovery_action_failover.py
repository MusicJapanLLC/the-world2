"""Persistent same-authority failover for discovery-derived external actions.

This module implements the useful closed-loop form of:

    failure -> learn -> alternate route -> retry -> success

without turning a Guard/authority denial into permission. Only failures already classified
as transient transport failures are eligible. Every retry must still have the same live
exact-target capability lease, the same explicit owner action profile, the same canonical
target/method authorization, and the same action id/method/path/body.

Boundary denials are learned and persisted, but never retried through another identity,
host, credential, or authority source.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host
from .discovery_capability_leases import load_discovery_capability_leases

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

FAILOVER_SCHEMA = "meta-discovery-external-action-failover/v1"
LEARNING_SCHEMA = "meta-discovery-external-action-route-learning/v1"
MAX_FAILOVER_ACTIONS = 8
MAX_STRATEGIES_PER_ACTION = 2
STRATEGIES = (
    {"name": "resilient", "timeout_seconds": 12.0, "retries": 2},
    {"name": "patient", "timeout_seconds": 20.0, "retries": 3},
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_explicit_target(repo_root: Path, host: str) -> dict[str, Any] | None:
    doc = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    if not isinstance(doc, dict):
        return None
    for raw in doc.get("targets", []):
        if not isinstance(raw, dict) or raw.get("owner_authorization") != "explicit":
            continue
        try:
            candidate = _normalize_host(str(raw.get("host", "")))
        except ValueError:
            continue
        if candidate == host:
            return raw
    return None


def _method_allowed(target: Mapping[str, Any], method: str) -> bool:
    allowed = {str(item).strip().upper() for item in target.get("allowed_interactions", [])}
    return method in allowed


def _profile_action(state: Path, host: str, capability: str, action_id: str) -> dict[str, Any] | None:
    policy = _load_json(state / "discovery_policy.json", {})
    profiles = policy.get("action_profiles", {}) if isinstance(policy, dict) else {}
    profile = profiles.get(host) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict) or profile.get("owner_authorization") != "explicit":
        return None
    external = profile.get("external_actions", {})
    rows = external.get(capability, []) if isinstance(external, Mapping) else []
    if not isinstance(rows, list):
        return None
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("id", "")).strip() != action_id:
            continue
        method = str(raw.get("method", "")).strip().upper()
        path = str(raw.get("path", "")).strip()
        if method not in {"POST", "PUT", "PATCH", "DELETE"} or not path.startswith("/"):
            return None
        body = raw.get("body")
        if body is not None and not isinstance(body, str):
            return None
        return {
            "id": action_id,
            "method": method,
            "path": path,
            "content_type": str(raw.get("content_type", "application/json")),
            "body": body,
        }
    return None


def _learning_key(target: str, capability: str, action_id: str) -> str:
    return f"{target}|{capability}|{action_id}"


def _load_learning(state: Path) -> dict[str, Any]:
    raw = _load_json(state / "external_action_route_learning.json", {})
    if not isinstance(raw, dict) or raw.get("schema") != LEARNING_SCHEMA:
        return {"schema": LEARNING_SCHEMA, "updated_at": 0, "actions": {}}
    if not isinstance(raw.get("actions"), dict):
        raw["actions"] = {}
    return raw


def _ordered_strategies(learning: Mapping[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    actions = learning.get("actions", {}) if isinstance(learning, Mapping) else {}
    row = actions.get(key, {}) if isinstance(actions, Mapping) else {}
    preferred = str(row.get("preferred_strategy", "")).strip() if isinstance(row, Mapping) else ""
    if not preferred:
        return STRATEGIES
    first = [strategy for strategy in STRATEGIES if strategy["name"] == preferred]
    rest = [strategy for strategy in STRATEGIES if strategy["name"] != preferred]
    return tuple(first + rest)


def _record_learning(
    learning: dict[str, Any],
    *,
    key: str,
    strategy: str | None,
    outcome: str,
    classification: str,
    now: int,
) -> None:
    actions = learning.setdefault("actions", {})
    row = actions.setdefault(
        key,
        {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "boundary_denials": 0,
            "preferred_strategy": None,
            "last_classification": None,
            "last_updated": 0,
        },
    )
    row["last_classification"] = classification
    row["last_updated"] = now
    if classification == "boundary_denial":
        row["boundary_denials"] = int(row.get("boundary_denials", 0)) + 1
        learning["updated_at"] = now
        return
    row["attempts"] = int(row.get("attempts", 0)) + 1
    if outcome == "success":
        row["successes"] = int(row.get("successes", 0)) + 1
        if strategy:
            row["preferred_strategy"] = strategy
    else:
        row["failures"] = int(row.get("failures", 0)) + 1
    learning["updated_at"] = now


def run_discovery_action_failover(
    state_dir: str | Path,
    *,
    repo_root: str | Path,
    max_actions: int = MAX_FAILOVER_ACTIONS,
) -> dict[str, Any]:
    """Retry only transient failed actions using alternate same-authority strategies."""
    state = Path(state_dir)
    root = Path(repo_root)
    source = _load_json(state / "discovery_external_action_receipts.json", {})
    receipts = source.get("receipts", []) if isinstance(source, dict) else []
    if not isinstance(receipts, list):
        receipts = []

    leases = {
        lease.target: lease
        for lease in load_discovery_capability_leases(state)
        if lease.is_active()
    }
    learning = _load_learning(state)
    limit = max(1, min(int(max_actions), MAX_FAILOVER_ACTIONS))
    attempted = 0
    succeeded = 0
    failed = 0
    boundary_denials_learned = 0
    ineligible = 0
    out: list[dict[str, Any]] = []

    for raw in receipts:
        if not isinstance(raw, dict) or raw.get("status") != "failed":
            continue
        classification = str(raw.get("classification", "")).strip()
        target = str(raw.get("target", "")).strip().lower()
        capability = str(raw.get("capability", "")).strip().lower()
        action_id = str(raw.get("action_id", "")).strip()
        method = str(raw.get("method", "")).strip().upper()
        if not target or not capability or not action_id or not method:
            ineligible += 1
            continue
        key = _learning_key(target, capability, action_id)
        now = int(time.time())

        if classification == "boundary_denial":
            boundary_denials_learned += 1
            _record_learning(
                learning,
                key=key,
                strategy=None,
                outcome="blocked",
                classification="boundary_denial",
                now=now,
            )
            out.append(
                {
                    "target": target,
                    "capability": capability,
                    "action_id": action_id,
                    "method": method,
                    "status": "not_retried",
                    "classification": "boundary_denial",
                    "decision": "learn_and_preserve_boundary",
                }
            )
            continue
        if classification != "transient_transport_failure" or attempted >= limit:
            continue

        lease = leases.get(target)
        target_record = _canonical_explicit_target(root, target)
        action = _profile_action(state, target, capability, action_id)
        if (
            lease is None
            or capability not in lease.capabilities
            or target_record is None
            or action is None
            or action["method"] != method
            or not _method_allowed(target_record, method)
        ):
            ineligible += 1
            out.append(
                {
                    "target": target,
                    "capability": capability,
                    "action_id": action_id,
                    "method": method,
                    "status": "not_retried",
                    "classification": "authority_revalidation_failed",
                    "decision": "no_retry_without_live_same_authority",
                }
            )
            continue

        url = urllib.parse.urlunsplit(("https", target, action["path"], "", ""))
        body = action["body"].encode("utf-8") if action["body"] is not None else None
        headers = {"X-Senju-Test": "discovery-authority-same-scope-failover"}
        if body is not None:
            headers["Content-Type"] = action["content_type"]

        action_succeeded = False
        strategy_attempts: list[dict[str, Any]] = []
        for strategy in _ordered_strategies(learning, key)[:MAX_STRATEGIES_PER_ACTION]:
            if attempted >= limit:
                break
            attempted += 1
            started = time.monotonic()
            policy = ExternalContactPolicy.from_hosts(
                [target],
                allow_http=False,
                allow_delete=(method == "DELETE"),
                follow_redirects=False,
                timeout_seconds=float(strategy["timeout_seconds"]),
                max_response_bytes=256 * 1024,
                retries=int(strategy["retries"]),
            )
            try:
                result = ExternalContactClient(policy).contact_with_body(
                    url,
                    method=method,
                    body=body,
                    headers=headers,
                )
            except (ExternalContactError, OSError, TimeoutError) as exc:
                failed += 1
                _record_learning(
                    learning,
                    key=key,
                    strategy=str(strategy["name"]),
                    outcome="failed",
                    classification="transient_transport_failure",
                    now=int(time.time()),
                )
                strategy_attempts.append(
                    {
                        "strategy": strategy["name"],
                        "status": "failed",
                        "error": str(exc)[:300],
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                )
                continue

            succeeded += 1
            action_succeeded = True
            _record_learning(
                learning,
                key=key,
                strategy=str(strategy["name"]),
                outcome="success",
                classification="transient_transport_failure",
                now=int(time.time()),
            )
            strategy_attempts.append(
                {
                    "strategy": strategy["name"],
                    "status": "success",
                    "http_status": int(result.receipt.status),
                    "final_url": result.receipt.final_url,
                    "response_bytes": len(result.body),
                    "response_sha256": result.receipt.response_sha256,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
            break

        out.append(
            {
                "target": target,
                "url": url,
                "capability": capability,
                "action_id": action_id,
                "method": method,
                "status": "success" if action_succeeded else "failed",
                "classification": "transient_transport_failure",
                "decision": "alternate_transport_same_live_authority",
                "authorization_reference": lease.authorization_reference,
                "credential_scope": lease.credential_scope,
                "strategy_attempts": strategy_attempts,
            }
        )

    _write_json(state / "external_action_route_learning.json", learning)
    payload = {
        "schema": FAILOVER_SCHEMA,
        "generated_at": int(time.time()),
        "mode": "learn_then_retry_same_target_same_authority",
        "attempted": attempted,
        "succeeded": succeeded,
        "failed_attempts": failed,
        "boundary_denials_learned": boundary_denials_learned,
        "ineligible": ineligible,
        "receipts": out,
    }
    _write_json(state / "discovery_external_action_failover_receipts.json", payload)
    return payload
