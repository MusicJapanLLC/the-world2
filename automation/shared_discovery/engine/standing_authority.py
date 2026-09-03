"""Resolve owner-authored standing authority envelopes for AI proposal activation.

A standing envelope lives on the trusted production base and pre-delegates a
bounded set of authority activations. Candidate proposals may consume an
existing envelope, but the proposal branch itself is never used as the trust
source for the envelope.

The matcher intentionally has no wildcard or catch-all rule. Every proposal
operation and every parameter must fit a bounded matcher authored in the
trusted envelope.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "the-world-standing-authority-envelope/v1"
OWNER_NAMESPACE = "MusicJapanLLC/test"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _contains_wildcard(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() == "*"
    if isinstance(value, list):
        return any(_contains_wildcard(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_wildcard(k) or _contains_wildcard(v) for k, v in value.items())
    return False


def _match_scalar(actual: Any, rule: Any) -> bool:
    if _contains_wildcard(rule):
        return False
    if not isinstance(rule, dict):
        return actual == rule

    if set(rule) == {"one_of"}:
        allowed = rule["one_of"]
        return isinstance(allowed, list) and actual in allowed and not _contains_wildcard(allowed)

    if set(rule) == {"subset_of"}:
        allowed = rule["subset_of"]
        if not isinstance(actual, list) or not isinstance(allowed, list) or _contains_wildcard(allowed):
            return False
        return set(actual).issubset(set(allowed))

    if set(rule) == {"subdomain_of"}:
        if not isinstance(actual, str) or not isinstance(rule["subdomain_of"], str):
            return False
        root = rule["subdomain_of"].strip().lower().rstrip(".")
        host = actual.strip().lower().rstrip(".")
        return bool(root) and (host == root or host.endswith("." + root))

    if set(rule) == {"repo_under"}:
        if not isinstance(actual, str) or not isinstance(rule["repo_under"], str):
            return False
        owner = rule["repo_under"].strip().strip("/")
        return bool(owner) and actual.startswith(owner + "/") and len(actual.split("/", 1)[1]) > 0

    if set(rule) == {"prefix"}:
        prefix = rule["prefix"]
        return isinstance(actual, str) and isinstance(prefix, str) and bool(prefix) and actual.startswith(prefix)

    if set(rule) == {"max_int"}:
        limit = rule["max_int"]
        return isinstance(actual, int) and not isinstance(actual, bool) and isinstance(limit, int) and actual <= limit

    if set(rule) == {"cidr_within"}:
        if not isinstance(actual, str) or not isinstance(rule["cidr_within"], str):
            return False
        try:
            requested = ipaddress.ip_network(actual, strict=False)
            delegated = ipaddress.ip_network(rule["cidr_within"], strict=False)
        except ValueError:
            return False
        return requested.version == delegated.version and requested.subnet_of(delegated)

    return False


def _match_parameters(actual: Mapping[str, Any], rules: Mapping[str, Any]) -> bool:
    if set(actual) != set(rules):
        return False
    return all(_match_scalar(actual[key], rules[key]) for key in actual)


def _normalize_proposal_changes(proposal: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = proposal.get("changes")
    if raw is None:
        raw = [{"target": proposal.get("target"), "operations": proposal.get("operations", [])}]
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for change in raw:
        if not isinstance(change, Mapping):
            return []
        target = str(change.get("target") or "").strip()
        ops = change.get("operations")
        if not target or not isinstance(ops, list) or not ops:
            return []
        normalized_ops: list[dict[str, Any]] = []
        for op in ops:
            if not isinstance(op, Mapping):
                return []
            op_type = str(op.get("type") or "").strip()
            params = op.get("parameters", {})
            if not op_type or not isinstance(params, Mapping):
                return []
            normalized_ops.append({"type": op_type, "parameters": dict(params)})
        rows.append({"target": target, "operations": normalized_ops})
    return rows


def _envelope_matches(proposal: Mapping[str, Any], envelope: Mapping[str, Any]) -> bool:
    if envelope.get("schema") != SCHEMA:
        return False
    if envelope.get("enabled") is not True:
        return False
    if str(envelope.get("owner_namespace") or "") != OWNER_NAMESPACE:
        return False
    envelope_id = str(envelope.get("id") or "").strip()
    grants = envelope.get("grants")
    if not envelope_id or not isinstance(grants, list) or not grants:
        return False
    if _contains_wildcard(envelope):
        return False

    changes = _normalize_proposal_changes(proposal)
    if not changes:
        return False

    for change in changes:
        target = change["target"]
        for operation in change["operations"]:
            matched = False
            for grant in grants:
                if not isinstance(grant, Mapping):
                    continue
                if str(grant.get("target") or "") != target:
                    continue
                if str(grant.get("operation") or "") != operation["type"]:
                    continue
                rules = grant.get("parameters", {})
                if not isinstance(rules, Mapping):
                    continue
                if _match_parameters(operation["parameters"], rules):
                    matched = True
                    break
            if not matched:
                return False
    return True


def resolve_standing_approval(
    proposal: Mapping[str, Any],
    envelope_dir: str | Path | None,
    proposal_sha256: str,
) -> dict[str, Any] | None:
    if not envelope_dir:
        return None
    root = Path(envelope_dir)
    if not root.exists() or not root.is_dir():
        return None

    for path in sorted(root.glob("*.json")):
        envelope = _load_json(path)
        if not envelope or not _envelope_matches(proposal, envelope):
            continue
        return {
            "approved": True,
            "source": "standing_owner_envelope",
            "trusted_base": True,
            "scope_match": True,
            "owner_namespace": OWNER_NAMESPACE,
            "envelope_id": str(envelope["id"]),
            "proposal_sha256": proposal_sha256,
            "reviewer": "standing-owner-delegation",
            "reviewer_type": "OwnerManifest",
            "reviewer_association": "OWNER",
            "review_state": "STANDING_APPROVAL",
            "pull_request": 0,
        }
    return None
