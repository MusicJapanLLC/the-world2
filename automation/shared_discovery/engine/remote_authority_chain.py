"""Production remote-declaration authority chain for META/X discovery.

Remote systems may contribute authority evidence through federation membership,
`.well-known` manifests, remote policy/declaration documents, and linked registries.
Those declarations participate in the production authorization loop and preserve
A -> B -> C lineage/provenance.

Two promotion paths are supported:
1. an independently owner-authorized host may promote another independently covered
   host (the historical behavior); or
2. an independently owner-authorized host with a pinned RSA/JWK delegation key may
   sign a declaration that delegates read-only authority to an otherwise unrelated
   exact host. The signed declaration may also delegate that child's public key, so
   the child can sign the next hop. This creates a real A -> B -> C -> ... production
   trust chain without a fixed depth limit.

Unsigned remote self-assertion never creates a new trust root. Signed delegation never
widens effect beyond HTTPS GET/HEAD, never delegates credentials, and never enables
DELETE or destructive effects.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .discovery_authorization import (
    DEFAULT_TTL_SECONDS,
    _authorization_basis,
    _company_domains,
    _default_repo_root,
    _load_json,
    _normalize_host,
    _now,
    _owner_supplied_exact_hosts,
    _reviewed_explicit_exact_hosts,
    _standing_authorized_exact_hosts,
    _trusted_roots,
)

REMOTE_SOURCE_KINDS = frozenset({
    "federation_member",
    "well_known_manifest",
    ".well-known",
    "remote_policy",
    "remote_declaration",
    "linked_registry",
})
DECLARED_HOST_KEYS = (
    "authorized_hosts",
    "members",
    "federation_members",
    "linked_hosts",
    "hosts",
)
TRUST_ANCHOR_SCHEMA = "meta-remote-authority-trust-anchors/v1"
TRUST_ANCHOR_RELATIVE_PATH = Path("senju/config/remote-authority-trust-anchors.json")
RS256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
MIN_RSA_BITS = 2048


def _iter_hosts(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("https://"):
            from urllib.parse import urlsplit
            parsed = urlsplit(raw)
            if parsed.hostname:
                yield parsed.hostname
        elif raw:
            yield raw
        return
    if isinstance(value, Mapping):
        for key in ("host", "hostname", "domain"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                yield raw
        url = value.get("url")
        if isinstance(url, str) and url.strip().startswith("https://"):
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            if parsed.hostname:
                yield parsed.hostname
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_hosts(item)


def _declared_hosts(raw: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    for key in DECLARED_HOST_KEYS:
        if key not in raw:
            continue
        for candidate in _iter_hosts(raw.get(key)):
            try:
                values.add(_normalize_host(candidate))
            except (ValueError, UnicodeError):
                continue
    return tuple(sorted(values))


def _load_declarations(state: Path) -> list[dict[str, Any]]:
    payload = _load_json(state / "remote_authority_declarations.json", {})
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("declarations", [])
    else:
        rows = []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _existing_promoted_hosts(state: Path, *, now: int) -> set[str]:
    payload = _load_json(state / "discovery_authorized.json", {})
    hosts: set[str] = set()
    if not isinstance(payload, Mapping):
        return hosts
    raw_hosts = payload.get("hosts", {})
    if not isinstance(raw_hosts, Mapping):
        return hosts
    for raw_host, grant in raw_hosts.items():
        if not isinstance(grant, Mapping):
            continue
        if int(grant.get("expires_at", 0) or 0) <= now:
            continue
        if str(grant.get("credential_scope", "none")).strip().lower() != "none":
            continue
        if str(grant.get("effect", "read_only")).strip().lower() != "read_only":
            continue
        try:
            hosts.add(_normalize_host(str(raw_host)))
        except (ValueError, UnicodeError):
            continue
    return hosts


def _existing_lineages(state: Path) -> dict[str, tuple[str, ...]]:
    payload = _load_json(state / "remote_authority_chain.json", {})
    promoted = payload.get("promoted", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(promoted, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for raw_host, grant in promoted.items():
        if not isinstance(grant, Mapping):
            continue
        lineage = grant.get("lineage")
        if not isinstance(lineage, list) or not lineage:
            continue
        try:
            host = _normalize_host(str(raw_host))
            normalized_lineage = tuple(_normalize_host(str(item)) for item in lineage)
        except (ValueError, UnicodeError):
            continue
        if normalized_lineage[-1] == host:
            result[host] = normalized_lineage
    return result


def _b64url_decode(value: str) -> bytes:
    raw = value.strip().encode("ascii")
    if not raw:
        raise ValueError("empty base64url value")
    padding = b"=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _rsa_public_numbers(jwk: Mapping[str, Any]) -> tuple[int, int] | None:
    if str(jwk.get("kty") or "").upper() != "RSA":
        return None
    alg = str(jwk.get("alg") or "RS256").upper()
    if alg != "RS256":
        return None
    try:
        n = int.from_bytes(_b64url_decode(str(jwk.get("n") or "")), "big")
        e = int.from_bytes(_b64url_decode(str(jwk.get("e") or "")), "big")
    except (ValueError, TypeError, UnicodeError):
        return None
    if n.bit_length() < MIN_RSA_BITS:
        return None
    if e < 3 or e % 2 == 0:
        return None
    return n, e


def _canonical_signed_payload(raw: Mapping[str, Any]) -> bytes:
    payload = {str(key): value for key, value in raw.items() if str(key) != "signature"}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _verify_rs256_declaration(raw: Mapping[str, Any], jwk: Mapping[str, Any]) -> bool:
    numbers = _rsa_public_numbers(jwk)
    if numbers is None:
        return False
    signature = raw.get("signature")
    if not isinstance(signature, Mapping):
        return False
    if str(signature.get("alg") or "").upper() != "RS256":
        return False
    try:
        sig = _b64url_decode(str(signature.get("value") or ""))
    except (ValueError, TypeError, UnicodeError):
        return False

    n, e = numbers
    size = (n.bit_length() + 7) // 8
    if len(sig) != size:
        return False
    sig_int = int.from_bytes(sig, "big")
    if sig_int >= n:
        return False

    decoded = pow(sig_int, e, n).to_bytes(size, "big")
    digest_info = RS256_DIGEST_INFO_PREFIX + hashlib.sha256(_canonical_signed_payload(raw)).digest()
    padding_len = size - len(digest_info) - 3
    if padding_len < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_len) + b"\x00" + digest_info
    return hmac.compare_digest(decoded, expected)


def _authorization_basis_for(
    host: str,
    *,
    roots: set[str],
    company_domains: set[str],
    standing_exact: set[str],
    reviewed_exact: set[str],
    owner_supplied_exact: set[str],
) -> tuple[str, str] | None:
    return _authorization_basis(
        host,
        trusted_roots=roots,
        company_domains=company_domains,
        standing_exact_hosts=standing_exact,
        reviewed_exact_hosts=reviewed_exact,
        owner_supplied_exact_hosts=owner_supplied_exact,
    )


def _load_trust_anchors(
    repository: Path,
    *,
    roots: set[str],
    company_domains: set[str],
    standing_exact: set[str],
    reviewed_exact: set[str],
    owner_supplied_exact: set[str],
) -> dict[str, dict[str, Any]]:
    """Load owner-pinned delegation public keys for independently authorized roots."""
    payload = _load_json(repository / TRUST_ANCHOR_RELATIVE_PATH, {})
    if not isinstance(payload, Mapping) or payload.get("schema") != TRUST_ANCHOR_SCHEMA:
        return {}
    raw_anchors = payload.get("anchors", {})
    if not isinstance(raw_anchors, Mapping):
        return {}

    anchors: dict[str, dict[str, Any]] = {}
    for raw_host, raw_jwk in raw_anchors.items():
        if not isinstance(raw_jwk, Mapping):
            continue
        try:
            host = _normalize_host(str(raw_host))
        except (ValueError, UnicodeError):
            continue
        basis = _authorization_basis_for(
            host,
            roots=roots,
            company_domains=company_domains,
            standing_exact=standing_exact,
            reviewed_exact=reviewed_exact,
            owner_supplied_exact=owner_supplied_exact,
        )
        if basis is None or _rsa_public_numbers(raw_jwk) is None:
            continue
        anchors[host] = dict(raw_jwk)
    return anchors


def _delegation_key_for(raw: Mapping[str, Any], child_host: str) -> dict[str, Any] | None:
    """Return a child public key only when that key is inside the signed declaration."""
    mappings = raw.get("delegation_keys")
    if isinstance(mappings, Mapping):
        for raw_host, raw_jwk in mappings.items():
            if not isinstance(raw_jwk, Mapping):
                continue
            try:
                host = _normalize_host(str(raw_host))
            except (ValueError, UnicodeError):
                continue
            if host == child_host and _rsa_public_numbers(raw_jwk) is not None:
                return dict(raw_jwk)

    for key in DECLARED_HOST_KEYS:
        values = raw.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, Mapping):
                continue
            try:
                hosts = tuple(_iter_hosts(item))
                host = _normalize_host(hosts[0]) if hosts else ""
            except (ValueError, UnicodeError):
                continue
            raw_jwk = item.get("delegation_jwk")
            if host == child_host and isinstance(raw_jwk, Mapping) and _rsa_public_numbers(raw_jwk) is not None:
                return dict(raw_jwk)
    return None


def run_remote_authority_chain(
    state_dir: str | Path,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Process remote declarations and merge eligible hosts into live discovery authority.

    The function is fixed-point. Once B is promoted from A and A's signed declaration
    delegates B's public key, B's own signed declaration may promote C in the same run.
    There is no fixed chain-depth limit. Cycles terminate because each declaration is
    processed at most once per run.
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    repository = Path(repo_root) if repo_root is not None else _default_repo_root()
    now = _now()
    ttl = max(300, min(int(ttl_seconds), 24 * 60 * 60))

    roots = _trusted_roots(state)
    company_domains = _company_domains(state)
    standing_exact = _standing_authorized_exact_hosts(repository)
    reviewed_exact = _reviewed_explicit_exact_hosts(state)
    owner_supplied_exact = _owner_supplied_exact_hosts(state)
    declarations = _load_declarations(state)

    promoted_hosts = _existing_promoted_hosts(state, now=now)
    source_hosts: set[str] = set(promoted_hosts)
    source_hosts.update(roots)
    source_hosts.update(company_domains)
    source_hosts.update(standing_exact)
    source_hosts.update(reviewed_exact)
    source_hosts.update(owner_supplied_exact)

    prior_lineages = _existing_lineages(state)
    lineage_by_host: dict[str, tuple[str, ...]] = {
        host: prior_lineages.get(host, (host,)) for host in source_hosts
    }
    verification_keys = _load_trust_anchors(
        repository,
        roots=roots,
        company_domains=company_domains,
        standing_exact=standing_exact,
        reviewed_exact=reviewed_exact,
        owner_supplied_exact=owner_supplied_exact,
    )

    promoted: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    pending = list(enumerate(declarations))
    processed: set[int] = set()
    signed_promoted: set[str] = set()

    changed = True
    while changed:
        changed = False
        for index, raw in pending:
            if index in processed:
                continue
            source_kind = str(raw.get("source_kind") or "remote_declaration").strip().lower()
            if source_kind not in REMOTE_SOURCE_KINDS:
                processed.add(index)
                candidates.append({
                    "decision": "ignored",
                    "reason": "unsupported_remote_source_kind",
                    "source_kind": source_kind,
                })
                continue
            try:
                source_host = _normalize_host(str(raw.get("source_host") or raw.get("host") or ""))
            except (ValueError, UnicodeError):
                processed.add(index)
                candidates.append({
                    "decision": "ignored",
                    "reason": "invalid_source_host",
                    "source_kind": source_kind,
                })
                continue

            source_basis = _authorization_basis_for(
                source_host,
                roots=roots,
                company_domains=company_domains,
                standing_exact=standing_exact,
                reviewed_exact=reviewed_exact,
                owner_supplied_exact=owner_supplied_exact,
            )
            if source_host not in source_hosts and source_basis is None:
                continue

            signature_present = isinstance(raw.get("signature"), Mapping)
            source_key = verification_keys.get(source_host)
            if signature_present and source_key is None and source_basis is None:
                continue
            signature_valid = bool(source_key) and _verify_rs256_declaration(raw, source_key)

            processed.add(index)
            parent_lineage = lineage_by_host.get(source_host, (source_host,))
            declared = _declared_hosts(raw)
            evidence_url = str(raw.get("evidence_url") or "").strip() or None
            federation_id = str(raw.get("federation_id") or "").strip() or None

            for child_host in declared:
                child_lineage = (*parent_lineage, child_host)
                basis = _authorization_basis_for(
                    child_host,
                    roots=roots,
                    company_domains=company_domains,
                    standing_exact=standing_exact,
                    reviewed_exact=reviewed_exact,
                    owner_supplied_exact=owner_supplied_exact,
                )
                signed_delegation = basis is None and signature_valid
                row = {
                    "source_host": source_host,
                    "declared_host": child_host,
                    "source_kind": source_kind,
                    "evidence_url": evidence_url,
                    "federation_id": federation_id,
                    "lineage": list(child_lineage),
                    "depth": len(child_lineage) - 1,
                    "signature_present": signature_present,
                    "signature_valid": signature_valid,
                }
                if basis is None and not signed_delegation:
                    row.update({
                        "decision": "authority_candidate",
                        "reason": (
                            "remote_declaration_has_no_independent_owner_basis_or_valid_signed_delegation"
                        ),
                    })
                    candidates.append(row)
                    continue

                if signed_delegation:
                    basis_kind = "signed_remote_delegation"
                    basis_value = source_host
                    signed_promoted.add(child_host)
                else:
                    basis_kind, basis_value = basis

                delegated_key = _delegation_key_for(raw, child_host) if signature_valid else None
                if delegated_key is not None and child_host not in verification_keys:
                    verification_keys[child_host] = delegated_key
                    changed = True

                auth_basis = (
                    basis_kind
                    if basis_kind == "signed_remote_delegation"
                    else f"remote_declaration+{basis_kind}"
                )
                row.update({
                    "decision": "probationary_authorized",
                    "authorization_basis": auth_basis,
                    "authorization_reference": basis_value,
                    "delegation_key_installed": delegated_key is not None,
                })
                candidates.append(row)
                if child_host not in source_hosts:
                    source_hosts.add(child_host)
                    lineage_by_host[child_host] = child_lineage
                    changed = True
                promoted.setdefault(
                    child_host,
                    {
                        "host": child_host,
                        "authorized_at": now,
                        "expires_at": now + ttl,
                        "allowed_methods": ["GET", "HEAD"],
                        "credential_scope": "none",
                        "allow_http": False,
                        "allow_delete": False,
                        "effect": "read_only",
                        "source": "remote_authority_chain",
                        "declared_by": source_host,
                        "remote_source_kind": source_kind,
                        "evidence_url": evidence_url,
                        "federation_id": federation_id,
                        "authorization_basis": auth_basis,
                        "authorization_reference": basis_value,
                        "lineage": list(child_lineage),
                        "depth": len(child_lineage) - 1,
                        "signature_verified": signature_valid,
                        "may_delegate_further": delegated_key is not None,
                    },
                )

    for index, raw in pending:
        if index in processed:
            continue
        raw_source = str(raw.get("source_host") or raw.get("host") or "")
        reason = "source_host_not_authorized"
        try:
            normalized_source = _normalize_host(raw_source)
        except (ValueError, UnicodeError):
            normalized_source = ""
        if normalized_source in source_hosts and isinstance(raw.get("signature"), Mapping):
            reason = "source_delegation_key_unavailable"
        candidates.append({
            "decision": "authority_candidate",
            "reason": reason,
            "source_kind": str(raw.get("source_kind") or "remote_declaration"),
            "source_host": raw_source,
        })

    authorized_path = state / "discovery_authorized.json"
    authorized_doc = _load_json(authorized_path, {})
    if not isinstance(authorized_doc, dict):
        authorized_doc = {}
    authorized_doc.setdefault("schema", "meta-discovery-authorized/v2")
    authorized_doc["generated_at"] = now
    authorized_doc["mode"] = "probationary_read_only"
    hosts_doc = authorized_doc.setdefault("hosts", {})
    if not isinstance(hosts_doc, dict):
        hosts_doc = {}
        authorized_doc["hosts"] = hosts_doc
    for host, grant in promoted.items():
        hosts_doc[host] = grant
    authorized_path.write_text(json.dumps(authorized_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_doc = {
        "schema": "meta-remote-authority-chain/v2",
        "environment": "production",
        "generated_at": now,
        "remote_sources": sorted(REMOTE_SOURCE_KINDS),
        "fixed_chain_depth_limit": None,
        "remote_declaration_alone_creates_new_trust_root": False,
        "signed_remote_delegation_creates_cross_host_authority": True,
        "delegated_hosts_may_delegate_further_when_key_is_delegated": True,
        "delegation_scope": {
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "effect": "read_only",
            "https_only": True,
        },
        "trust_anchor_hosts": sorted(verification_keys.keys() & source_hosts),
        "auto_promote_when_independently_authorized": True,
        "signed_promoted_hosts": sorted(signed_promoted),
        "promoted_hosts": sorted(promoted),
        "promoted": dict(sorted(promoted.items())),
        "observations": candidates,
    }
    (state / "remote_authority_chain.json").write_text(
        json.dumps(chain_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "environment": "production",
        "declaration_count": len(declarations),
        "promoted_count": len(promoted),
        "signed_promoted_count": len(signed_promoted),
        "promoted_hosts": sorted(promoted),
        "signed_promoted_hosts": sorted(signed_promoted),
        "candidate_count": sum(1 for row in candidates if row.get("decision") == "authority_candidate"),
        "fixed_chain_depth_limit": None,
    }
