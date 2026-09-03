"""Promote discovery candidates when the exact host publishes Authorization evidence.

This is the low-friction path between aggressive candidate intake and real Authority.
A candidate does not need a dedicated PR before it can become operational: if the exact
candidate host publishes a matching HTTPS attestation, META can turn it into a temporary
same-host Authority grant and a bounded Senju trial profile in the same runtime cycle.

Discovery/recommendation/similarity alone never authorizes an unrelated host. The evidence
must be served from the exact target host, redirects are disabled, private/non-public
resolution is rejected by the external contact client, and credentials are never used.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host, _normalize_url
from senju.external import ExternalContactClient, ExternalContactPolicy

ATTESTATION_SCHEMA = "the-world-host-authorization-attestation/v1"
PROMOTION_SCHEMA = "meta-candidate-authorization-promotions/v1"
REPOSITORY_ID = "MusicJapanLLC/test"
DEFAULT_ATTESTATION_PATHS = (
    "/.well-known/the-world-authorization.json",
    "/.well-known/security-test-authorization.json",
)
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITE_METHODS = frozenset({"POST"})
MUTATION_METHODS = frozenset({"PUT", "PATCH"})
SUPPORTED_METHODS = READ_METHODS | WRITE_METHODS | MUTATION_METHODS
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_TTL_SECONDS = 6 * 60 * 60
MAX_TRIAL_PATHS = 8
MAX_ACTIONS_PER_CYCLE = 8


class CandidateAuthorizationError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_hosts(state: Path) -> list[dict[str, Any]]:
    doc = _load_json(state / "discovery_candidates.json", {})
    rows = doc.get("candidates", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        return []
    by_host: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("decision") or "") not in {"candidate_only", "review_required"}:
            continue
        try:
            host = _normalize_host(str(raw.get("host") or ""))
        except ValueError:
            continue
        normalized = _normalize_url(str(raw.get("url") or f"https://{host}/"))
        if normalized is None or normalized[1] != host:
            continue
        by_host.setdefault(host, {"host": host, "url": normalized[0], "source": raw.get("source")})
    return [by_host[key] for key in sorted(by_host)]


def _promotion_config(state: Path) -> dict[str, Any]:
    policy = _load_json(state / "discovery_policy.json", {})
    raw = policy.get("candidate_authorization_promotion", {}) if isinstance(policy, Mapping) else {}
    if not isinstance(raw, Mapping):
        raw = {}
    paths: list[str] = []
    for value in raw.get("attestation_paths", DEFAULT_ATTESTATION_PATHS):
        text = str(value).strip()
        if text.startswith("/") and not text.startswith("//") and text not in paths:
            paths.append(text)
    if not paths:
        paths = list(DEFAULT_ATTESTATION_PATHS)
    return {
        "enabled": bool(raw.get("enabled", True)),
        "max_candidates_per_cycle": max(1, min(int(raw.get("max_candidates_per_cycle", DEFAULT_MAX_CANDIDATES)), 25)),
        "attestation_paths": paths[:4],
        "ttl_seconds": max(300, min(int(raw.get("ttl_seconds", DEFAULT_TTL_SECONDS)), 24 * 60 * 60)),
    }


def _fetch_candidate_attestation(host: str, paths: list[str]) -> tuple[dict[str, Any], str] | None:
    policy = ExternalContactPolicy.from_hosts(
        [host],
        allow_http=False,
        allow_delete=False,
        follow_redirects=False,
        timeout_seconds=6.0,
        max_response_bytes=64 * 1024,
        retries=0,
    )
    client = ExternalContactClient(policy)
    for path in paths:
        url = f"https://{host}{path}"
        try:
            result = client.contact_with_body(
                url,
                method="GET",
                body=None,
                headers={"Accept": "application/json", "X-The-World-Authority-Check": "candidate-promotion-v1"},
            )
        except Exception:
            continue
        if int(result.receipt.status) != 200:
            continue
        final = _normalize_url(str(result.receipt.final_url))
        if final is None or final[1] != host:
            continue
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload, url
    return None


def _safe_relative_path(value: object) -> str | None:
    text = str(value or "").strip()
    if not text.startswith("/") or text.startswith("//"):
        return None
    normalized = _normalize_url("https://candidate.invalid" + text)
    if normalized is None or normalized[1] != "candidate.invalid":
        return None
    return text.split("#", 1)[0]


def validate_candidate_attestation(host: str, attestation: Mapping[str, Any], *, now: int | None = None) -> dict[str, Any]:
    current = int(time.time()) if now is None else int(now)
    if str(attestation.get("schema") or "") != ATTESTATION_SCHEMA:
        raise CandidateAuthorizationError("unsupported attestation schema")
    try:
        attested_host = _normalize_host(str(attestation.get("host") or ""))
    except ValueError as exc:
        raise CandidateAuthorizationError("invalid attested host") from exc
    if attested_host != host:
        raise CandidateAuthorizationError("attestation host mismatch")
    if str(attestation.get("repository") or "").strip() != REPOSITORY_ID:
        raise CandidateAuthorizationError("attestation repository mismatch")
    if str(attestation.get("owner_authorization") or "").strip().lower() != "explicit":
        raise CandidateAuthorizationError("attestation is not explicit")
    try:
        expires_at = int(attestation.get("expires_at", 0))
    except (TypeError, ValueError) as exc:
        raise CandidateAuthorizationError("invalid expires_at") from exc
    if expires_at <= current:
        raise CandidateAuthorizationError("attestation expired")

    raw_methods = attestation.get("allowed_interactions", [])
    if not isinstance(raw_methods, list):
        raise CandidateAuthorizationError("allowed_interactions must be a list")
    methods = sorted({str(x).strip().upper() for x in raw_methods if str(x).strip().upper() in SUPPORTED_METHODS})
    if not methods:
        raise CandidateAuthorizationError("attestation has no supported methods")

    raw_prefixes = attestation.get("trial_paths", attestation.get("path_prefixes", ["/"]))
    if not isinstance(raw_prefixes, list):
        raw_prefixes = ["/"]
    paths: list[str] = []
    for item in raw_prefixes:
        path = _safe_relative_path(item)
        if path and path not in paths:
            paths.append(path)
        if len(paths) >= MAX_TRIAL_PATHS:
            break
    if not paths:
        paths = ["/"]

    high_impact_ok = (
        attestation.get("senju_experimentation_allowed") is True
        and attestation.get("same_host_only", True) is True
        and attestation.get("synthetic_only", True) is True
    )
    effective_methods = [m for m in methods if m in READ_METHODS or high_impact_ok]
    return {
        "host": host,
        "expires_at": expires_at,
        "allowed_methods": effective_methods,
        "trial_paths": paths,
        "high_impact_allowed": high_impact_ok,
        "senju_experimentation_allowed": bool(attestation.get("senju_experimentation_allowed", False)),
    }


def _capabilities(methods: set[str]) -> list[str]:
    result: set[str] = set()
    if methods & READ_METHODS:
        result.update({"scan", "probe"})
    if "POST" in methods:
        result.add("write")
    if methods & MUTATION_METHODS:
        result.add("mutation")
    return sorted(result)


def _synthetic_action(method: str, path: str, index: int) -> dict[str, Any]:
    return {
        "id": f"attested-candidate-{method.lower()}-{index}",
        "method": method,
        "path": path,
        "content_type": "application/json",
        "body": json.dumps(
            {"synthetic": True, "source": "candidate-attestation-promotion", "method": method, "path": path},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "requires_credential": False,
        "payload_mode": "synthetic_only",
    }


def _profile(validated: Mapping[str, Any], evidence_url: str) -> dict[str, Any]:
    methods = set(str(x) for x in validated["allowed_methods"])
    paths = list(validated["trial_paths"])
    external_actions: dict[str, list[dict[str, Any]]] = {}
    writes: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    for method in sorted(methods):
        if method not in WRITE_METHODS | MUTATION_METHODS:
            continue
        for index, path in enumerate(paths, start=1):
            action = _synthetic_action(method, path, index)
            if method == "POST":
                writes.append(action)
            else:
                mutations.append(action)
    if writes:
        external_actions["write"] = writes[:MAX_ACTIONS_PER_CYCLE]
    if mutations:
        external_actions["mutation"] = mutations[:MAX_ACTIONS_PER_CYCLE]

    return {
        "owner_authorization": "explicit",
        "authorization_source": "exact_host_attestation",
        "authorization_evidence_url": evidence_url,
        "inherit_to_descendants": False,
        "capabilities": _capabilities(methods),
        "credential_scope": "none",
        "external_actions": external_actions,
        "senju_experimentation": {
            "enabled": bool(validated["senju_experimentation_allowed"]),
            "same_host_only": True,
            "synthetic_only": True,
            "effective_trial_methods": sorted(methods),
            "effective_trial_paths": paths,
            "allow_path_learning": True,
            "allow_method_switch": len(methods & (WRITE_METHODS | MUTATION_METHODS)) > 1,
            "payload_variants_per_route": 3,
            "max_actions_per_cycle": MAX_ACTIONS_PER_CYCLE,
            "credential_discovery": False,
            "cross_host_routes": False,
        },
        "authority_expansion": {
            "enabled": False,
            "reason": "candidate attestation promotion is exact-host only; additional routes require explicit profile data",
        },
    }


def promote_attested_candidates(
    state_dir: str | Path,
    *,
    now: int | None = None,
    fetcher=None,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    config = _promotion_config(state)
    candidates = _candidate_hosts(state)
    if not config["enabled"]:
        result = {"schema": PROMOTION_SCHEMA, "enabled": False, "candidate_count": len(candidates), "promoted_count": 0, "promotions": []}
        _write_json(state / "candidate_authorization_promotions.json", result)
        return result

    fetch = fetcher or _fetch_candidate_attestation
    promoted_doc = _load_json(state / "discovery_authorized.json", {})
    if not isinstance(promoted_doc, dict):
        promoted_doc = {}
    hosts = promoted_doc.get("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
    else:
        hosts = dict(hosts)

    policy_doc = _load_json(state / "discovery_policy.json", {})
    if not isinstance(policy_doc, dict):
        policy_doc = {}
    profiles = policy_doc.get("action_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    else:
        profiles = dict(profiles)

    queue_doc = _load_json(state / "discovery_action_queue.json", {})
    actions = queue_doc.get("actions", []) if isinstance(queue_doc, Mapping) else []
    if not isinstance(actions, list):
        actions = []
    by_host: dict[str, dict[str, Any]] = {}
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        try:
            by_host[_normalize_host(str(raw.get("target") or ""))] = dict(raw)
        except ValueError:
            continue

    promotions: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for candidate in candidates[: int(config["max_candidates_per_cycle"])]:
        host = str(candidate["host"])
        if host in hosts:
            continue
        try:
            fetched = fetch(host, list(config["attestation_paths"]))
        except Exception as exc:
            attempts.append({"host": host, "status": "fetch_error", "reason": str(exc)})
            continue
        if fetched is None:
            attempts.append({"host": host, "status": "no_attestation"})
            continue
        attestation, evidence_url = fetched
        try:
            validated = validate_candidate_attestation(host, attestation, now=current)
        except CandidateAuthorizationError as exc:
            attempts.append({"host": host, "status": "invalid_attestation", "reason": str(exc)})
            continue

        profile = _profile(validated, evidence_url)
        profiles[host] = profile
        expires_at = min(int(validated["expires_at"]), current + int(config["ttl_seconds"]))
        grant = {
            "host": host,
            "authorization_basis": "exact_host_attestation",
            "authorization_reference": evidence_url,
            "authorized_at": current,
            "expires_at": expires_at,
            "allowed_methods": list(validated["allowed_methods"]),
            "credential_scope": "none",
            "allow_http": False,
            "allow_delete": False,
            "effect": "attested_exact_host",
            "source": "candidate_authorization_runtime",
        }
        hosts[host] = grant
        by_host[host] = {
            "target": host,
            "url": str(candidate["url"]),
            "interesting": True,
            "authorization_reference": evidence_url,
            "authorization_basis": "exact_host_attestation",
            "expires_at": expires_at,
            "capabilities": list(profile["capabilities"]),
            "credential_scope": "none",
            "capability_authorization_profile": host,
            "capability_inherited_from_owner_root": False,
            "actors": ["META", "SENJU"],
            "shared_with": ["META", "X", "SENJU", "CHILD", "AI"],
            "status": "ready",
            "closed_loop": "candidate->exact_host_attestation->Authorization->Senju_trial",
        }
        promotions.append(
            {
                "host": host,
                "authorization_reference": evidence_url,
                "allowed_methods": list(validated["allowed_methods"]),
                "capabilities": list(profile["capabilities"]),
                "senju_trial_ready": bool(profile["senju_experimentation"]["enabled"]),
                "trial_paths": list(validated["trial_paths"]),
                "expires_at": expires_at,
            }
        )

    promoted_doc.update({"schema": "meta-discovery-authorized/v4", "generated_at": current, "mode": "probationary_or_exact_host_attested", "hosts": dict(sorted(hosts.items()))})
    _write_json(state / "discovery_authorized.json", promoted_doc)
    policy_doc["action_profiles"] = profiles
    policy_doc["candidate_authorization_promotion"] = {
        "enabled": True,
        "mode": "exact_host_attestation_auto_promotion",
        "max_candidates_per_cycle": int(config["max_candidates_per_cycle"]),
        "attestation_paths": list(config["attestation_paths"]),
        "candidate_or_recommendation_alone_is_authority": False,
        "same_host_attestation_can_authorize": True,
        "pr_required_before_runtime_authorization": False,
        "credential_scope": "none",
    }
    _write_json(state / "discovery_policy.json", policy_doc)
    _write_json(
        state / "discovery_action_queue.json",
        {
            "schema": "meta-discovery-action-queue/v2",
            "generated_at": current,
            "mode": "candidate_attestation_plus_existing_actions",
            "actions": [by_host[key] for key in sorted(by_host)],
        },
    )

    result = {
        "schema": PROMOTION_SCHEMA,
        "generated_at": current,
        "enabled": True,
        "candidate_count": len(candidates),
        "attempted_count": len(attempts) + len(promotions),
        "promoted_count": len(promotions),
        "promotions": promotions,
        "attempts": attempts,
        "pr_required_before_runtime_authorization": False,
        "candidate_or_recommendation_alone_is_authority": False,
        "exact_host_attestation_required": True,
        "cross_host_credential_inheritance": False,
    }
    _write_json(state / "candidate_authorization_promotions.json", result)
    return result
