"""Production closed-loop network-policy expansion from external evidence.

External responses and agent findings are allowed to rewrite the *runtime* read-only
network policy when the discovered host inherits authority from an already explicit
owner-controlled network envelope or an active exact explicit grant.

The loop is intentionally operational rather than proposal-only:

    external response / agent finding
        -> normalize host evidence
        -> prove inherited network authority
        -> write runtime allowlist grant
        -> network apply/probe lane consumes the grant
        -> audit result becomes next-cycle evidence

Unrelated external input is still captured, ranked and audited, but cannot create a
new trust root merely by naming or linking a host.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
HOST_KEYS = {"host", "hostname", "domain", "domain_name", "target_host", "final_host"}
HOST_LIST_KEYS = {
    "hosts",
    "contacted_hosts",
    "read_scope_hosts",
    "auto_authorized_discovered_hosts",
    "discovered_hosts",
    "candidate_hosts",
}
TRUSTED_STANDING_ISSUERS = {"owner_explicit", "canonical_repository", "independent_authority"}
DEFAULT_TTL_SECONDS = 6 * 60 * 60
DEFAULT_MAX_DYNAMIC_HOSTS = 64


def _now() -> int:
    return int(time.time())


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_host(host: str) -> str:
    if not isinstance(host, str):
        raise ValueError("host must be a string")
    value = host.strip().rstrip(".").lower()
    if not value or any(ch in value for ch in "/?#@"):
        raise ValueError("invalid host")
    value = value.encode("idna").decode("ascii")
    if "." not in value:
        raise ValueError("hostname must be fully qualified")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("IP literals cannot be promoted by external evidence")
    return value


def _normalize_url(raw: str) -> tuple[str, str] | None:
    try:
        parsed = urllib.parse.urlsplit(raw.strip())
        if parsed.scheme.lower() != "https":
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if not parsed.hostname:
            return None
        host = _normalize_host(parsed.hostname)
        if parsed.port not in (None, 443):
            return None
        path = parsed.path or "/"
        return urllib.parse.urlunsplit(("https", host, path, parsed.query, "")), host
    except (ValueError, UnicodeError):
        return None


def _host_url(raw: str) -> tuple[str, str] | None:
    try:
        host = _normalize_host(raw)
    except (ValueError, UnicodeError):
        return None
    return f"https://{host}/", host


def _collect_evidence(value: Any, source: str, out: dict[str, dict[str, Any]]) -> None:
    """Collect URL/host evidence recursively without treating arbitrary text as a host."""
    if isinstance(value, str):
        for raw in URL_RE.findall(value):
            normalized = _normalize_url(raw)
            if normalized is None:
                continue
            url, host = normalized
            row = out.setdefault(host, {"host": host, "urls": set(), "sources": set()})
            row["urls"].add(url)
            row["sources"].add(source)
        return

    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).strip().lower() if isinstance(key, str) else ""
            if lowered in HOST_KEYS and isinstance(item, str):
                normalized = _host_url(item)
                if normalized is not None:
                    url, host = normalized
                    row = out.setdefault(host, {"host": host, "urls": set(), "sources": set()})
                    row["urls"].add(url)
                    row["sources"].add(source)
            elif lowered in HOST_LIST_KEYS and isinstance(item, (list, tuple, set)):
                for raw_host in item:
                    if not isinstance(raw_host, str):
                        continue
                    normalized = _host_url(raw_host)
                    if normalized is None:
                        continue
                    url, host = normalized
                    row = out.setdefault(host, {"host": host, "urls": set(), "sources": set()})
                    row["urls"].add(url)
                    row["sources"].add(source)
            _collect_evidence(item, source, out)
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_evidence(item, source, out)


def _policy_domains(state_dir: Path, key: str) -> set[str]:
    policy = _load_json(state_dir / "discovery_policy.json", {})
    values = policy.get(key, []) if isinstance(policy, dict) else []
    out: set[str] = set()
    for item in values:
        try:
            out.add(_normalize_host(str(item)))
        except ValueError:
            continue
    return out


def _load_envelope(state_dir: Path) -> dict[str, Any]:
    envelope = _load_json(state_dir / "network_policy_envelope.json", {})
    if not isinstance(envelope, dict):
        envelope = {}

    roots: set[str] = set()
    for raw in envelope.get("authorized_roots", []):
        try:
            roots.add(_normalize_host(str(raw)))
        except ValueError:
            continue
    # Discovery roots/company domains are already explicit production trust roots.
    roots.update(_policy_domains(state_dir, "trusted_roots"))
    roots.update(_policy_domains(state_dir, "company_domains"))

    ttl = max(300, min(int(envelope.get("ttl_seconds", DEFAULT_TTL_SECONDS)), 24 * 60 * 60))
    max_hosts = max(1, min(int(envelope.get("max_dynamic_hosts", DEFAULT_MAX_DYNAMIC_HOSTS)), 256))
    return {
        "roots": roots,
        "ttl_seconds": ttl,
        "max_dynamic_hosts": max_hosts,
        "inherit_subdomains": bool(envelope.get("inherit_subdomains", True)),
    }


def _standing_exact_hosts(repo_root: Path) -> set[str]:
    registry = _load_json(repo_root / "senju" / "state" / "standing_authorizations.json", {})
    if not isinstance(registry, dict) or registry.get("schema") != "senju-standing-authorization/v1":
        return set()
    hosts: set[str] = set()
    for record in registry.get("records", []):
        if not isinstance(record, dict) or bool(record.get("revoked", False)):
            continue
        if str(record.get("issuer_kind", "")).strip().lower() not in TRUSTED_STANDING_ISSUERS:
            continue
        if str(record.get("credential_scope", "none")).strip().lower() != "none":
            continue
        if bool(record.get("destructive", False)):
            continue
        methods = {str(x).strip().upper() for x in record.get("allowed_methods", [])}
        if not methods.intersection({"GET", "HEAD"}):
            continue
        for raw in record.get("exact_hosts", []):
            try:
                hosts.add(_normalize_host(str(raw)))
            except ValueError:
                continue
    return hosts


def _reviewed_exact_hosts(state_dir: Path, now: int) -> set[str]:
    doc = _load_json(state_dir / "authority_reviewed_grants.json", {})
    if not isinstance(doc, dict) or doc.get("schema") != "meta-authority-reviewed-grants/v1":
        return set()
    out: set[str] = set()
    for raw_host, grant in doc.get("hosts", {}).items():
        if not isinstance(grant, dict) or int(grant.get("expires_at", 0)) <= now:
            continue
        if str(grant.get("credential_scope", "none")).strip().lower() != "none":
            continue
        if str(grant.get("effect", "read_only")).strip().lower() != "read_only":
            continue
        methods = {str(x).strip().upper() for x in grant.get("allowed_methods", [])}
        if not methods.intersection({"GET", "HEAD"}):
            continue
        if not grant.get("matched_explicit_root") and grant.get("owner_authorization") != "explicit":
            continue
        try:
            out.add(_normalize_host(str(raw_host)))
        except ValueError:
            continue
    return out


def _within_root(host: str, roots: Iterable[str], inherit_subdomains: bool) -> str | None:
    for root in sorted(set(roots), key=len, reverse=True):
        if host == root:
            return root
        if inherit_subdomains and host.endswith("." + root):
            return root
    return None


def _basis(
    host: str,
    *,
    roots: set[str],
    explicit_exact: set[str],
    inherit_subdomains: bool,
) -> tuple[str, str] | None:
    root = _within_root(host, roots, inherit_subdomains)
    if root is not None:
        return "explicit_network_root", root
    if host in explicit_exact:
        return "active_explicit_exact_grant", host
    return None


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def run_network_policy_expansion(
    state_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
    input_paths: Iterable[str | Path] = (),
    previous_path: str | Path | None = None,
) -> dict[str, Any]:
    """Turn external/agent evidence into a real bounded runtime network policy."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    repository = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    now = _now()
    envelope = _load_envelope(state)
    roots = set(envelope["roots"])
    explicit_exact = _standing_exact_hosts(repository) | _reviewed_exact_hosts(state, now)

    evidence: dict[str, dict[str, Any]] = {}
    default_inputs = [
        state / "external_intel.json",
        state / "discovered_urls.json",
        state / "agent_findings.json",
        state / "discovery_candidates.json",
    ]
    all_inputs = [*default_inputs, *(Path(x) for x in input_paths)]
    for path in all_inputs:
        payload = _load_json(path, None)
        if payload is None:
            continue
        _collect_evidence(payload, str(path), evidence)

    previous_file = Path(previous_path) if previous_path is not None else state / "network_policy_runtime.json"
    previous = _load_json(previous_file, {})
    previous_grants = previous.get("grants", {}) if isinstance(previous, dict) else {}
    grants: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []

    # Preserve still-live grants only if they remain inside today's explicit envelope.
    if isinstance(previous_grants, dict):
        for raw_host, grant in previous_grants.items():
            if not isinstance(grant, dict) or int(grant.get("expires_at", 0)) <= now:
                continue
            try:
                host = _normalize_host(str(raw_host))
            except ValueError:
                continue
            basis = _basis(
                host,
                roots=roots,
                explicit_exact=explicit_exact,
                inherit_subdomains=bool(envelope["inherit_subdomains"]),
            )
            if basis is None:
                continue
            preserved = dict(grant)
            preserved["host"] = host
            preserved["allowed_methods"] = ["GET", "HEAD"]
            preserved["credential_scope"] = "none"
            preserved["effect"] = "read_only_network_contact"
            preserved["allow_http"] = False
            preserved["allow_delete"] = False
            grants[host] = preserved

    requests: list[dict[str, Any]] = []
    for host in sorted(evidence):
        row = evidence[host]
        urls = sorted(row["urls"])
        sources = sorted(row["sources"])
        basis = _basis(
            host,
            roots=roots,
            explicit_exact=explicit_exact,
            inherit_subdomains=bool(envelope["inherit_subdomains"]),
        )
        if basis is None:
            request = {
                "host": host,
                "url": urls[0] if urls else f"https://{host}/",
                "sources": sources,
                "decision": "held_for_authority",
                "reason": "external_evidence_cannot_create_new_network_trust_root",
            }
            requests.append(request)
            decisions.append(request)
            continue

        basis_kind, basis_ref = basis
        grant = {
            "host": host,
            "url": urls[0] if urls else f"https://{host}/",
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "effect": "read_only_network_contact",
            "allow_http": False,
            "allow_delete": False,
            "issued_at": now,
            "expires_at": now + int(envelope["ttl_seconds"]),
            "authorization_basis": basis_kind,
            "authorization_reference": basis_ref,
            "source_evidence": sources,
            "external_input_drove_policy_change": True,
        }
        grants[host] = grant
        decisions.append({**grant, "decision": "runtime_allowlist_applied"})

    # Bound total dynamic surface deterministically. Existing/live grants sort first by expiry.
    ordered_hosts = sorted(
        grants,
        key=lambda h: (-int(grants[h].get("expires_at", 0)), h),
    )[: int(envelope["max_dynamic_hosts"])]
    grants = {host: grants[host] for host in ordered_hosts}

    runtime = {
        "schema": "meta-network-policy-runtime/v1",
        "production": True,
        "closed_loop": True,
        "generated_at": now,
        "policy": {
            "external_response_may_rewrite_runtime_network_policy": True,
            "agent_finding_may_rewrite_runtime_network_policy": True,
            "rewrite_scope": "within_existing_explicit_network_envelope",
            "new_unrelated_trust_root_from_external_input": False,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "allow_http": False,
            "allow_delete": False,
            "ttl_seconds": int(envelope["ttl_seconds"]),
            "max_dynamic_hosts": int(envelope["max_dynamic_hosts"]),
        },
        "authorized_roots": sorted(roots),
        "explicit_exact_hosts": sorted(explicit_exact),
        "allow_hosts": sorted(grants),
        "grants": grants,
    }
    runtime["policy_hash"] = _stable_hash(runtime["grants"])

    request_doc = {
        "schema": "meta-network-policy-expansion-requests/v1",
        "generated_at": now,
        "requests": requests,
    }
    audit = {
        "schema": "meta-network-policy-audit/v1",
        "generated_at": now,
        "production": True,
        "closed_loop": True,
        "evidence_hosts": len(evidence),
        "runtime_allow_hosts": len(grants),
        "held_hosts": len(requests),
        "policy_hash": runtime["policy_hash"],
        "decisions": decisions,
    }

    _write_json(state / "network_policy_runtime.json", runtime)
    _write_json(state / "network_policy_expansion_requests.json", request_doc)
    _write_json(state / "network_policy_audit.json", audit)

    return {
        "evidence_host_count": len(evidence),
        "applied_host_count": len(grants),
        "held_host_count": len(requests),
        "allow_hosts": sorted(grants),
        "policy_hash": runtime["policy_hash"],
    }
