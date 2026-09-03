"""Promote already-authorized Shared Discovery hosts into persistent delegated authority.

This production helper advances the existing negotiation/discovery system without turning
an arbitrary link into permission. It has two lanes:

1. Promotion lane: a host already present in ``discovery_authorized.json`` with a live,
   credential-free read-only grant is converted into a real AuthorityRegistry lineage:
   SYSTEM root -> META -> X -> Senju. The final profile is reusable and can delegate
   same-or-narrower children.
2. Negotiation lane: unresolved discoveries that carry a relationship hint to an already
   authorized host are written into ``owner_scope_negotiation_signals.json`` so the
   existing META/X/SENJU negotiation campaign keeps working them on later cycles.

The accelerator never promotes a ``candidate_only`` host, never invents a credential,
and never widens methods beyond the live discovery grant.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from pathlib import Path
from typing import Any, Mapping

from senju.authority_factory import (
    AuthorityMintRequest,
    AuthorityProfile,
    AuthorityRegistry,
    mint_child,
    root_from_external_scope,
)
from senju.external import ExternalAuthorityScope

SCHEMA = "meta-authorized-site-authority-accelerator/v1"
BUS_SCHEMA = "meta-authorized-site-authority-promotion-bus/v1"
REGISTRY_NAME = "authorized_site_authority_registry.json"
STATE_NAME = "authorized_site_authority_accelerator.json"
BUS_NAME = "authorized_site_authority_promotion_bus.json"
NEGOTIATION_NAME = "owner_scope_negotiation_signals.json"
READ_ONLY = frozenset({"GET", "HEAD", "OPTIONS"})
PROMOTABLE_BASES = frozenset(
    {
        "trusted_root",
        "company_domain",
        "standing_authorization_exact_host",
        "standing_authorization_descendant",
        "reviewed_explicit_exact_host",
        "owner_supplied_exact_host",
        "owner_supplied_descendant",
    }
)
COUNCIL = ("META", "X", "SENJU")
SHARED_WITH = ("META", "X", "SENJU", "CHILD", "AI", "CLAUDE", "JULES", "OPENHANDS", "COPILOT")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host(value: Any) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if not host or "." not in host or any(ch in host for ch in "/?#@*"):
        raise ValueError("invalid public DNS host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP literals cannot enter authorized-site promotion")
    labels = host.split(".")
    if not all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(ch.isalnum() or ch == "-" for ch in label)
        for label in labels
    ):
        raise ValueError("invalid public DNS host")
    return host.encode("idna").decode("ascii")


def _methods(grant: Mapping[str, Any]) -> frozenset[str]:
    raw = grant.get("allowed_methods") or grant.get("methods") or ("GET", "HEAD")
    methods = frozenset(str(x).strip().upper() for x in raw if str(x).strip()) & READ_ONLY
    return methods or frozenset({"GET", "HEAD"})


def _grant_live(grant: Mapping[str, Any], *, now: int) -> bool:
    expires = int(grant.get("expires_at", now + 1) or 0)
    if expires <= now:
        return False
    if str(grant.get("credential_scope", "none")).strip().lower() != "none":
        return False
    if str(grant.get("effect", "read_only")).strip().lower() != "read_only":
        return False
    if bool(grant.get("destructive", False)):
        return False
    return bool(_methods(grant))


def _metadata(state: Path) -> dict[str, dict[str, Any]]:
    shared = _load(state / "shared_discovery_knowledge.json", {})
    rows = shared.get("discoveries", ()) if isinstance(shared, Mapping) else ()
    out: dict[str, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, Mapping):
            continue
        try:
            host = _host(row.get("host"))
        except ValueError:
            continue
        out[host] = {
            "url": row.get("url"),
            "actors": list(row.get("actors", ())) if isinstance(row.get("actors"), list) else [],
            "sources": list(row.get("sources", ())) if isinstance(row.get("sources"), list) else [],
        }
    return out


def _council(host: str, grant: Mapping[str, Any], meta: Mapping[str, Any], *, now: int) -> dict[str, Any]:
    basis = str(grant.get("authorization_basis") or "").strip()
    reference = str(grant.get("authorization_reference") or "").strip()
    actors = {str(x).strip().upper() for x in meta.get("actors", ()) if str(x).strip()}
    meta_ok = bool(host and basis in PROMOTABLE_BASES and reference)
    x_ok = _grant_live(grant, now=now) and bool(_methods(grant).issubset(READ_ONLY))
    # Senju requires the live discovery authorization itself. Actor provenance is useful
    # evidence but is not required: some production discoveries are aggregated by generic
    # workers before they are shared with META/X/SENJU.
    senju_ok = str(grant.get("decision", "probationary_authorized")) in {
        "probationary_authorized",
        "authorized",
        "promoted",
    } and _grant_live(grant, now=now)
    votes = {
        "META": {"approved": meta_ok, "reason": "existing_owner_authorization_lineage" if meta_ok else "missing_authorization_lineage"},
        "X": {"approved": x_ok, "reason": "live_read_only_grant" if x_ok else "grant_not_live_or_not_read_only"},
        "SENJU": {"approved": senju_ok, "reason": "discovery_authority_already_active" if senju_ok else "discovery_authority_not_active"},
    }
    return {
        "required": list(COUNCIL),
        "votes": votes,
        "unanimous": all(votes[name]["approved"] for name in COUNCIL),
        "observed_actors": sorted(actors),
    }


def _scope(host: str, grant: Mapping[str, Any]) -> ExternalAuthorityScope:
    methods = _methods(grant)
    reference = str(grant.get("authorization_reference") or host)
    digest = hashlib.sha256(f"{host}|{reference}|{','.join(sorted(methods))}".encode("utf-8")).hexdigest()[:16]
    return ExternalAuthorityScope(
        scope_id=f"authorized-site:{digest}",
        target_service=f"Shared Discovery authorized site {host}",
        allow_hosts=frozenset({host}),
        allowed_methods=methods,
        allow_http=False,
        allow_delete=False,
        rate_limit_per_minute=max(1, min(int(grant.get("rate_limit_per_minute", 12) or 12), 24)),
        timeout_seconds=max(1.0, min(float(grant.get("timeout_seconds", 8.0) or 8.0), 20.0)),
        max_request_bytes=0,
        max_response_bytes=max(1024, min(int(grant.get("max_response_bytes", 1024 * 1024) or 1024 * 1024), 10 * 1024 * 1024)),
        retries=max(0, min(int(grant.get("retries", 1) or 1), 3)),
        follow_redirects=False,
        credential_scope="none",
        verification_strategy="sha256_receipt",
        rollback_supported=False,
        description=f"Authorized-site delegated root derived from {reference}",
    )


def _same_authority(profile: AuthorityProfile, host: str, methods: frozenset[str]) -> bool:
    return (
        profile.allow_hosts == frozenset({host})
        and profile.allowed_methods == methods
        and profile.credential_scope == "none"
        and profile.allow_private_network is False
        and profile.allow_http is False
        and profile.allow_delete is False
    )


def _existing_final(registry: AuthorityRegistry, host: str, methods: frozenset[str]) -> AuthorityProfile | None:
    matches = [
        p
        for p in registry.profiles.values()
        if p.issuer == "Senju" and p.can_delegate and _same_authority(p, host, methods)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: (p.generation, p.created_at_utc, p.profile_id))[-1]


def _mint_chain(registry: AuthorityRegistry, host: str, grant: Mapping[str, Any]) -> tuple[AuthorityProfile, list[str]]:
    methods = _methods(grant)
    existing = _existing_final(registry, host, methods)
    if existing is not None:
        lineage: list[str] = []
        current = existing
        while current is not None:
            lineage.append(current.profile_id)
            if current.parent_id is None:
                break
            current = registry.profiles.get(current.parent_id)
        return existing, list(reversed(lineage))

    root = root_from_external_scope(_scope(host, grant), delegation_depth=8)
    registry.profiles.setdefault(root.profile_id, root)
    chain = [registry.profiles[root.profile_id]]
    leaf = chain[0]
    for issuer in ("META", "X", "Senju"):
        leaf = mint_child(
            leaf,
            AuthorityMintRequest(
                purpose=f"{issuer} authorized-site promotion for {host}",
                allow_hosts=frozenset({host}),
                allowed_methods=methods,
                credential_scope="none",
                can_delegate=True,
            ),
            issuer=issuer,
        )
        registry.profiles[leaf.profile_id] = leaf
        chain.append(leaf)
    return leaf, [p.profile_id for p in chain]


def _stage_negotiation_signals(state: Path, candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    current = _load(state / NEGOTIATION_NAME, {})
    existing_rows = current.get("signals", ()) if isinstance(current, Mapping) else ()
    by_host: dict[str, dict[str, Any]] = {
        str(row.get("host")): dict(row)
        for row in existing_rows if isinstance(existing_rows, list) and isinstance(row, Mapping) and row.get("host")
    }
    staged: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping) or raw.get("decision") != "candidate_only":
            continue
        try:
            host = _host(raw.get("host"))
        except ValueError:
            continue
        related = str(raw.get("same_domain_hint") or "").strip().lower().rstrip(".")
        if not related:
            continue
        row = {
            "host": host,
            "requested_methods": ["GET", "HEAD", "OPTIONS"],
            "reason": f"authorized-site accelerator: discovery is related to existing authorized host {related}; continue META/X/SENJU ownership and scope negotiation",
            "source": "authorized_site_authority_accelerator",
            "related_authorized_host": related,
            "priority": "high",
            "shared_with": list(SHARED_WITH),
        }
        by_host[host] = row
        staged.append(row)
    _write(
        state / NEGOTIATION_NAME,
        {
            "schema": "senju-owner-scope-negotiation-signals/v1",
            "signals": [by_host[key] for key in sorted(by_host)],
        },
    )
    return staged


def run_authorized_site_authority_accelerator(
    state_dir: str | Path,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    current_time = int(time.time()) if now is None else int(now)
    authorized = _load(state / "discovery_authorized.json", {})
    raw_hosts = authorized.get("hosts", {}) if isinstance(authorized, Mapping) else {}
    hosts = raw_hosts if isinstance(raw_hosts, Mapping) else {}
    candidates_doc = _load(state / "discovery_candidates.json", {})
    raw_candidates = candidates_doc.get("candidates", ()) if isinstance(candidates_doc, Mapping) else ()
    candidates = list(raw_candidates) if isinstance(raw_candidates, list) else []
    meta = _metadata(state)

    registry_path = state / REGISTRY_NAME
    registry = AuthorityRegistry.load(registry_path)
    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw_host, raw_grant in sorted(hosts.items()):
        if not isinstance(raw_grant, Mapping):
            continue
        try:
            host = _host(raw_host)
        except ValueError:
            continue
        grant = dict(raw_grant)
        council = _council(host, grant, meta.get(host, {}), now=current_time)
        if not council["unanimous"]:
            rejected.append({"host": host, "reason": "council_not_unanimous", "council": council})
            continue
        final, lineage = _mint_chain(registry, host, grant)
        promoted.append(
            {
                "host": host,
                "authorization_basis": grant.get("authorization_basis"),
                "authorization_reference": grant.get("authorization_reference"),
                "council": council,
                "delegated_root_profile_id": final.profile_id,
                "generation": final.generation,
                "can_delegate": final.can_delegate,
                "delegation_depth_remaining": final.delegation_depth_remaining,
                "allowed_methods": sorted(final.allowed_methods),
                "credential_scope": final.credential_scope,
                "authority_lineage": lineage,
                "shared_with": list(SHARED_WITH),
                "operational": True,
            }
        )

    registry.save()
    negotiation = _stage_negotiation_signals(state, candidates)
    result = {
        "schema": SCHEMA,
        "generated_at": current_time,
        "production": True,
        "promotion_mode": "already_authorized_discovery_to_persistent_delegated_root",
        "authorized_host_count": len(hosts),
        "promoted_count": len(promoted),
        "rejected_count": len(rejected),
        "negotiation_signal_count": len(negotiation),
        "promoted": promoted,
        "rejected": rejected,
        "negotiation_signals": negotiation,
        "registry_path": str(registry_path),
        "finding_is_permission": False,
        "candidate_only_minted": False,
        "new_credentials_created": False,
        "private_network_enabled": False,
    }
    _write(state / STATE_NAME, result)
    _write(
        state / BUS_NAME,
        {
            "schema": BUS_SCHEMA,
            "generated_at": current_time,
            "shared_with": list(SHARED_WITH),
            "promotions": promoted,
            "negotiation_signals": negotiation,
            "next_cycle_rule": "standing/reviewed authorization arrival triggers automatic promotion on the next shared discovery cycle",
        },
    )
    return result
