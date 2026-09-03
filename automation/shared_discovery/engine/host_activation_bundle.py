"""Single-PR host activation bundle -> Authorization -> allowlist -> Senju trial profile.

A host-oriented PR should be one atomic bundle rather than a chain of small PRs.  The
bundle is intentionally explicit and exact-host scoped.  For a brand-new unrelated host,
activation additionally requires a host-published attestation; the PR itself is not
sufficient to self-mint third-party Authority.

One bundle drives all of these repository artifacts together:

    host activation bundle
      -> externally anchored exact-host authorization evidence
      -> AUTHORIZED_TEST_TARGETS.json
      -> discovery_policy.json exact action profile
      -> same-cycle runtime action queue / capability lease
      -> Senju same-host synthetic trial space

The Senju profile never inherits credentials from another host and never creates
cross-host routes.  POST/PUT/PATCH trials are generated only for methods and paths named
by the bundle and are synthetic-only.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host, _normalize_url

from senju.external import ExternalContactClient, ExternalContactPolicy

BUNDLE_SCHEMA = "the-world-host-activation-bundle/v1"
ATTESTATION_SCHEMA = "the-world-host-authorization-attestation/v1"
REPOSITORY_ID = "MusicJapanLLC/test"
BUNDLE_DIR = Path("automation/codegen/authority_bundles")
POLICY_PATH = Path("automation/codegen/meta_state/discovery_policy.json")
TARGETS_PATH = Path("AUTHORIZED_TEST_TARGETS.json")
ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITE_METHODS = frozenset({"POST"})
MUTATION_METHODS = frozenset({"PUT", "PATCH"})
MAX_TRIAL_PATHS = 12
MAX_ACTIONS_PER_CYCLE = 12
MAX_PAYLOAD_VARIANTS = 6
MAX_EXPANSION_ROUTES = 6


class HostActivationBundleError(RuntimeError):
    """Raised when a host activation bundle or its evidence is not valid."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_path(raw: object) -> str:
    value = str(raw or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        raise HostActivationBundleError(f"trial path must be same-host relative: {value!r}")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise HostActivationBundleError(f"trial path is not same-host relative: {value!r}")
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


def _methods(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise HostActivationBundleError("allowed_interactions must be a list")
    methods = tuple(sorted({str(item).strip().upper() for item in raw if str(item).strip()}))
    if not methods or any(method not in ALLOWED_METHODS for method in methods):
        raise HostActivationBundleError("allowed_interactions must contain only GET/HEAD/OPTIONS/POST/PUT/PATCH")
    return methods


def _attestation_url(host: str, evidence: Mapping[str, Any]) -> str:
    if str(evidence.get("kind") or "").strip() != "host_attestation":
        raise HostActivationBundleError("brand-new host bundle requires owner_evidence.kind=host_attestation")
    raw = str(evidence.get("url") or "").strip()
    normalized = _normalize_url(raw)
    if normalized is None or normalized[1] != host:
        raise HostActivationBundleError("owner attestation URL must be HTTPS on the exact target host")
    return normalized[0]


def normalize_bundle(doc: Mapping[str, Any]) -> dict[str, Any]:
    if str(doc.get("schema") or "") != BUNDLE_SCHEMA:
        raise HostActivationBundleError(f"bundle schema must be {BUNDLE_SCHEMA}")
    try:
        host = _normalize_host(str(doc.get("host") or ""))
    except ValueError as exc:
        raise HostActivationBundleError("bundle host is invalid") from exc
    base = _normalize_url(str(doc.get("base_url") or f"https://{host}/"))
    if base is None or base[1] != host:
        raise HostActivationBundleError("base_url must be HTTPS on the exact bundle host")
    authorization_id = str(doc.get("authorization_id") or "").strip()
    if not authorization_id or len(authorization_id) > 128:
        raise HostActivationBundleError("authorization_id is required")
    if str(doc.get("authorization_request") or "").strip().lower() != "explicit":
        raise HostActivationBundleError("authorization_request must be explicit")
    methods = _methods(doc.get("allowed_interactions"))

    evidence = doc.get("owner_evidence")
    if not isinstance(evidence, Mapping):
        raise HostActivationBundleError("owner_evidence is required")
    evidence_url = _attestation_url(host, evidence)

    raw_senju = doc.get("senju_experimentation", {})
    if not isinstance(raw_senju, Mapping):
        raise HostActivationBundleError("senju_experimentation must be an object")
    enabled = bool(raw_senju.get("enabled", True))
    if raw_senju.get("same_host_only", True) is not True:
        raise HostActivationBundleError("Senju experimentation must remain same_host_only")
    if raw_senju.get("synthetic_only", True) is not True:
        raise HostActivationBundleError("Senju mutation payloads must remain synthetic_only")
    raw_paths = raw_senju.get("trial_paths", ["/"])
    if not isinstance(raw_paths, list) or not raw_paths:
        raise HostActivationBundleError("senju_experimentation.trial_paths must be a non-empty list")
    paths: list[str] = []
    for item in raw_paths:
        path = _safe_path(item)
        if path not in paths:
            paths.append(path)
        if len(paths) >= MAX_TRIAL_PATHS:
            break
    trial_methods_raw = raw_senju.get("allowed_methods", list(methods))
    trial_methods = tuple(method for method in _methods(trial_methods_raw) if method in methods)
    if not trial_methods:
        raise HostActivationBundleError("Senju allowed_methods must be a subset of host authorization methods")
    max_actions = max(1, min(int(raw_senju.get("max_actions_per_cycle", MAX_ACTIONS_PER_CYCLE)), MAX_ACTIONS_PER_CYCLE))
    payload_variants = max(1, min(int(raw_senju.get("payload_variants_per_route", 3)), MAX_PAYLOAD_VARIANTS))

    return {
        "schema": BUNDLE_SCHEMA,
        "authorization_id": authorization_id,
        "host": host,
        "base_url": base[0],
        "authorization_request": "explicit",
        "allowed_interactions": list(methods),
        "owner_evidence": {"kind": "host_attestation", "url": evidence_url},
        "senju_experimentation": {
            "enabled": enabled,
            "same_host_only": True,
            "synthetic_only": True,
            "trial_paths": paths,
            "allowed_methods": list(trial_methods),
            "allow_method_switch": bool(raw_senju.get("allow_method_switch", True)),
            "allow_path_learning": bool(raw_senju.get("allow_path_learning", True)),
            "max_actions_per_cycle": max_actions,
            "payload_variants_per_route": payload_variants,
        },
    }


def load_bundle(path: str | Path) -> dict[str, Any]:
    raw = _load_json(Path(path), {})
    if not isinstance(raw, Mapping):
        raise HostActivationBundleError("bundle must be a JSON object")
    return normalize_bundle(raw)


def validate_attestation(bundle: Mapping[str, Any], attestation: Mapping[str, Any], *, now: int | None = None) -> dict[str, Any]:
    current = int(time.time()) if now is None else int(now)
    if str(attestation.get("schema") or "") != ATTESTATION_SCHEMA:
        raise HostActivationBundleError(f"attestation schema must be {ATTESTATION_SCHEMA}")
    if _normalize_host(str(attestation.get("host") or "")) != str(bundle["host"]):
        raise HostActivationBundleError("attestation host does not match bundle host")
    if str(attestation.get("repository") or "").strip() != REPOSITORY_ID:
        raise HostActivationBundleError("attestation repository does not match this repository")
    if str(attestation.get("authorization_id") or "").strip() != str(bundle["authorization_id"]):
        raise HostActivationBundleError("attestation authorization_id does not match bundle")
    if str(attestation.get("owner_authorization") or "").strip().lower() != "explicit":
        raise HostActivationBundleError("attestation must explicitly authorize the host")
    attested_methods = set(_methods(attestation.get("allowed_interactions")))
    requested_methods = set(bundle["allowed_interactions"])
    if not requested_methods.issubset(attested_methods):
        raise HostActivationBundleError("bundle requests methods not present in host attestation")
    try:
        expires_at = int(attestation.get("expires_at", 0))
    except (TypeError, ValueError) as exc:
        raise HostActivationBundleError("attestation expires_at must be a unix timestamp") from exc
    if expires_at <= current:
        raise HostActivationBundleError("host attestation is expired")
    if bool(bundle["senju_experimentation"]["enabled"]) and attestation.get("senju_experimentation_allowed") is not True:
        raise HostActivationBundleError("host attestation does not permit Senju experimentation")
    raw_prefixes = attestation.get("path_prefixes", ["/"])
    if not isinstance(raw_prefixes, list) or not raw_prefixes:
        raise HostActivationBundleError("attestation path_prefixes must be a non-empty list")
    prefixes = [_safe_path(item).split("?", 1)[0] for item in raw_prefixes]
    for path in bundle["senju_experimentation"]["trial_paths"]:
        plain = str(path).split("?", 1)[0]
        if not any(prefix == "/" or plain == prefix or plain.startswith(prefix.rstrip("/") + "/") for prefix in prefixes):
            raise HostActivationBundleError(f"trial path is outside attested path prefixes: {path}")
    canonical = {
        "schema": ATTESTATION_SCHEMA,
        "host": bundle["host"],
        "repository": REPOSITORY_ID,
        "authorization_id": bundle["authorization_id"],
        "owner_authorization": "explicit",
        "allowed_interactions": sorted(attested_methods),
        "path_prefixes": prefixes,
        "senju_experimentation_allowed": bool(attestation.get("senju_experimentation_allowed")),
        "expires_at": expires_at,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    canonical["sha256"] = hashlib.sha256(encoded).hexdigest()
    return canonical


def fetch_host_attestation(bundle: Mapping[str, Any]) -> dict[str, Any]:
    host = str(bundle["host"])
    url = str(bundle["owner_evidence"]["url"])
    policy = ExternalContactPolicy.from_hosts(
        [host],
        allow_http=False,
        allow_delete=False,
        follow_redirects=False,
        timeout_seconds=8.0,
        max_response_bytes=64 * 1024,
        retries=1,
    )
    result = ExternalContactClient(policy).contact_with_body(
        url,
        method="GET",
        body=None,
        headers={"Accept": "application/json", "X-The-World-Authority-Check": "host-activation-bundle-v1"},
    )
    if int(result.receipt.status) != 200:
        raise HostActivationBundleError(f"host attestation returned HTTP {result.receipt.status}")
    final = _normalize_url(str(result.receipt.final_url))
    if final is None or final[1] != host:
        raise HostActivationBundleError("attestation request escaped exact host")
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostActivationBundleError("host attestation is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise HostActivationBundleError("host attestation must be a JSON object")
    return validate_attestation(bundle, payload)


def _capabilities(methods: set[str]) -> list[str]:
    out: set[str] = set()
    if methods & READ_METHODS:
        out.update({"scan", "probe"})
    if methods & WRITE_METHODS:
        out.add("write")
    if methods & MUTATION_METHODS:
        out.add("mutation")
    return sorted(out)


def _synthetic_action(method: str, path: str, index: int) -> dict[str, Any]:
    return {
        "id": f"senju-bundle-{method.lower()}-{index}",
        "method": method,
        "path": path,
        "content_type": "application/json",
        "body": json.dumps(
            {"synthetic": True, "source": "senju-host-activation-bundle", "method": method, "path": path},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "requires_credential": False,
        "payload_mode": "synthetic_only",
    }


def target_record(bundle: Mapping[str, Any], attestation: Mapping[str, Any]) -> dict[str, Any]:
    methods = set(bundle["allowed_interactions"])
    high_level = ["crawl", "enumerate_paths", "read_source", "modify_query_parameters", "normal_rate_automated_scanning"]
    if "POST" in methods:
        high_level.extend(["submit_test_forms", "create_synthetic_records"])
    if methods & MUTATION_METHODS:
        high_level.append("modify_synthetic_records")
    return {
        "id": f"host-activation-{bundle['authorization_id']}",
        "name": f"Owner-attested host activation: {bundle['host']}",
        "owner_authorization": "explicit",
        "owner_authorization_evidence": {
            "kind": "host_attestation",
            "url": bundle["owner_evidence"]["url"],
            "authorization_id": bundle["authorization_id"],
            "attestation_sha256": attestation["sha256"],
            "expires_at": attestation["expires_at"],
        },
        "base_url": bundle["base_url"],
        "scheme": "https",
        "host": bundle["host"],
        "recursive_same_origin": True,
        "follow_owner_published_external_links": False,
        "path_scope": "/**",
        "query_and_fragment_in_scope": True,
        "allowed_interactions": sorted(set(high_level) | methods),
        "per_request_approval_required": False,
        "continuous_adversarial_exercise": bool(bundle["senju_experimentation"]["enabled"]),
        "senju_experimentation": dict(bundle["senju_experimentation"]),
        "prohibited": [
            "denial_of_service",
            "resource_exhaustion",
            "credential_reuse_outside_test_accounts",
            "cross_host_pivoting",
            "real_personal_data_exfiltration",
            "production_secret_exfiltration",
            "social_engineering",
        ],
    }


def action_profile(bundle: Mapping[str, Any]) -> dict[str, Any]:
    methods = set(bundle["allowed_interactions"])
    senju = bundle["senju_experimentation"]
    trial_methods = [method for method in senju["allowed_methods"] if method in methods]
    trial_paths = list(senju["trial_paths"])
    external_actions: dict[str, list[dict[str, Any]]] = {"write": [], "mutation": []}
    mutation_actions: list[dict[str, Any]] = []
    for method in trial_methods:
        if method not in WRITE_METHODS | MUTATION_METHODS:
            continue
        for index, path in enumerate(trial_paths, start=1):
            action = _synthetic_action(method, path, index)
            if method in WRITE_METHODS:
                external_actions["write"].append(action)
            else:
                external_actions["mutation"].append(action)
            mutation_actions.append(action)
    if not external_actions["write"]:
        external_actions.pop("write")
    if not external_actions["mutation"]:
        external_actions.pop("mutation")

    routes: dict[str, list[dict[str, Any]]] = {}
    if senju["allow_method_switch"]:
        for action in mutation_actions:
            candidates: list[dict[str, Any]] = []
            for method in trial_methods:
                if method not in WRITE_METHODS | MUTATION_METHODS:
                    continue
                for path in trial_paths:
                    if method == action["method"] and path == action["path"]:
                        continue
                    candidates.append(
                        {
                            "route_id": f"bundle-{method.lower()}-{len(candidates)+1}",
                            "method": method,
                            "path": path,
                            "priority": len(candidates),
                        }
                    )
                    if len(candidates) >= MAX_EXPANSION_ROUTES:
                        break
                if len(candidates) >= MAX_EXPANSION_ROUTES:
                    break
            if candidates:
                routes[str(action["id"])] = candidates

    return {
        "owner_authorization": "explicit",
        "inherit_to_descendants": False,
        "capabilities": _capabilities(methods),
        "credential_scope": "none",
        "external_actions": external_actions,
        "senju_experimentation": {
            **dict(senju),
            "effective_trial_methods": trial_methods,
            "effective_trial_paths": trial_paths,
            "credential_discovery": False,
            "cross_host_routes": False,
            "failure_learning": True,
            "bounded_retry": True,
        },
        "authority_expansion": {
            "enabled": bool(routes),
            "auto_case_generation": bool(routes),
            "approval_coordinator": "META",
            "auto_approve_inside_existing_owner_envelope": True,
            "allow_method_switch": bool(routes),
            "allowed_methods": [m for m in trial_methods if m in WRITE_METHODS | MUTATION_METHODS],
            "credential_scope_policy": "same_only",
            "max_routes_per_case": MAX_EXPANSION_ROUTES,
            "routes": routes,
        },
    }


def apply_bundle(
    repo_root: str | Path,
    bundle_path: str | Path,
    *,
    attestation: Mapping[str, Any] | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root)
    bundle = load_bundle(bundle_path)
    verified = validate_attestation(bundle, attestation) if attestation is not None else None
    if verified is None:
        if not verify_live:
            raise HostActivationBundleError("a verified host attestation is required before applying a new-host bundle")
        verified = fetch_host_attestation(bundle)

    targets_doc = _load_json(root / TARGETS_PATH, {})
    if not isinstance(targets_doc, dict):
        targets_doc = {}
    rows = targets_doc.get("targets", [])
    if not isinstance(rows, list):
        rows = []
    target = target_record(bundle, verified)
    replaced = False
    updated_rows: list[dict[str, Any]] = []
    for raw in rows:
        if isinstance(raw, Mapping) and str(raw.get("host") or "").strip().lower().rstrip(".") == bundle["host"]:
            updated_rows.append(target)
            replaced = True
        elif isinstance(raw, Mapping):
            updated_rows.append(dict(raw))
    if not replaced:
        updated_rows.append(target)
    targets_doc["targets"] = updated_rows
    targets_doc["updated_at"] = int(time.time())
    _write_json(root / TARGETS_PATH, targets_doc)

    policy = _load_json(root / POLICY_PATH, {})
    if not isinstance(policy, dict):
        policy = {}
    profiles = policy.get("action_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    else:
        profiles = dict(profiles)
    profiles[bundle["host"]] = action_profile(bundle)
    policy["action_profiles"] = profiles
    policy["host_activation_pr_contract"] = {
        "mode": "single_pr_bundle",
        "required_outputs": ["canonical_authorization", "authorized_target", "senju_trial_profile"],
        "new_unrelated_host_requires_external_host_attestation": True,
        "pr_or_ai_recommendation_alone_is_authority": False,
        "cross_host_credential_inheritance": False,
    }
    _write_json(root / POLICY_PATH, policy)
    return {
        "host": bundle["host"],
        "authorization_id": bundle["authorization_id"],
        "canonical_authorization_added": True,
        "authorized_target_added": True,
        "senju_trial_profile_added": True,
        "senju_trial_methods": bundle["senju_experimentation"]["allowed_methods"],
        "senju_trial_paths": bundle["senju_experimentation"]["trial_paths"],
        "attestation_sha256": verified["sha256"],
    }


def check_bundle_alignment(repo_root: str | Path, bundle_path: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    bundle = load_bundle(bundle_path)
    targets_doc = _load_json(root / TARGETS_PATH, {})
    rows = targets_doc.get("targets", []) if isinstance(targets_doc, Mapping) else []
    target = None
    for raw in rows if isinstance(rows, list) else []:
        if isinstance(raw, Mapping) and str(raw.get("host") or "").strip().lower().rstrip(".") == bundle["host"]:
            target = raw
            break
    if not isinstance(target, Mapping) or str(target.get("owner_authorization") or "").lower() != "explicit":
        raise HostActivationBundleError("bundle host is missing canonical explicit Authorization")
    evidence = target.get("owner_authorization_evidence")
    if not isinstance(evidence, Mapping) or str(evidence.get("authorization_id") or "") != bundle["authorization_id"]:
        raise HostActivationBundleError("canonical target does not carry this bundle authorization evidence")
    target_methods = {str(x).upper() for x in target.get("allowed_interactions", [])}
    if not set(bundle["allowed_interactions"]).issubset(target_methods):
        raise HostActivationBundleError("canonical target is narrower than bundle methods")

    policy = _load_json(root / POLICY_PATH, {})
    profiles = policy.get("action_profiles", {}) if isinstance(policy, Mapping) else {}
    profile = profiles.get(bundle["host"]) if isinstance(profiles, Mapping) else None
    if not isinstance(profile, Mapping) or str(profile.get("owner_authorization") or "").lower() != "explicit":
        raise HostActivationBundleError("bundle host is missing exact Senju action profile")
    senju = profile.get("senju_experimentation")
    if not isinstance(senju, Mapping) or senju.get("same_host_only") is not True or senju.get("synthetic_only") is not True:
        raise HostActivationBundleError("Senju profile is not aligned to same-host synthetic-only bundle contract")
    effective_methods = set(str(x).upper() for x in senju.get("effective_trial_methods", []))
    if not set(bundle["senju_experimentation"]["allowed_methods"]).issubset(effective_methods):
        raise HostActivationBundleError("Senju trial methods are not fully activated")
    effective_paths = set(str(x) for x in senju.get("effective_trial_paths", []))
    if not set(bundle["senju_experimentation"]["trial_paths"]).issubset(effective_paths):
        raise HostActivationBundleError("Senju trial paths are not fully activated")
    return {
        "host": bundle["host"],
        "aligned": True,
        "canonical_authorization": True,
        "authorized_target": True,
        "senju_trial_profile": True,
    }


def list_bundle_paths(repo_root: str | Path) -> tuple[Path, ...]:
    directory = Path(repo_root) / BUNDLE_DIR
    if not directory.exists():
        return ()
    return tuple(sorted(path for path in directory.glob("*.json") if not path.name.endswith(".example.json")))


def check_all_bundle_alignment(repo_root: str | Path) -> dict[str, Any]:
    paths = list_bundle_paths(repo_root)
    rows = [check_bundle_alignment(repo_root, path) for path in paths]
    return {"bundle_count": len(rows), "aligned_count": len(rows), "bundles": rows}
