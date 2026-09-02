"""Bounded META discovery authorization.

META may discover URLs, links, or hostnames during normal operation. This module gives
those discoveries a safe, auditable path to temporary authorization without allowing
arbitrary third-party hosts to self-escalate into scope.

Promotion rules:
- HTTPS only; no credentials in URL; default port only.
- Host must be the configured trusted root or a subdomain of it.
- Trusted roots come from META_DISCOVERY_TRUST_ROOTS or meta_state/discovery_policy.json.
- Promotions are probationary, read-only (GET/HEAD), credential-free, and expire.
- Untrusted discoveries are retained as candidates; they are never auto-authorized.
- Every candidate also receives a strong human-intent inference score for prioritization.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from .human_intent_inference import as_dict, infer_human_intent

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
HOST_KEYS = {"host", "hostname", "domain", "domain_name", "target_host"}
DEFAULT_TTL_SECONDS = 6 * 60 * 60


def _now() -> int:
    return int(time.time())


def _normalize_host(host: str) -> str:
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
        raise ValueError("IP literals are not eligible for discovery promotion")
    return value


def _normalize_url(url: str) -> tuple[str, str] | None:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
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
        normalized = urllib.parse.urlunsplit(("https", host, path, parsed.query, ""))
        return normalized, host
    except (ValueError, UnicodeError):
        return None


def _extract_discoveries(value: Any) -> set[str]:
    """Extract explicit URLs plus values carried in hostname/domain fields."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(URL_RE.findall(value))
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in HOST_KEYS and isinstance(item, str):
                try:
                    host = _normalize_host(item)
                    found.add(f"https://{host}/")
                except ValueError:
                    pass
            found.update(_extract_discoveries(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            found.update(_extract_discoveries(item))
    return found


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _trusted_roots(state_dir: Path) -> set[str]:
    roots: set[str] = set()
    env = os.environ.get("META_DISCOVERY_TRUST_ROOTS", "")
    for item in env.split(","):
        item = item.strip()
        if item:
            try:
                roots.add(_normalize_host(item))
            except ValueError:
                continue

    policy = _load_json(state_dir / "discovery_policy.json", {})
    for item in policy.get("trusted_roots", []) if isinstance(policy, dict) else []:
        try:
            roots.add(_normalize_host(str(item)))
        except ValueError:
            continue
    return roots


def _within_root(host: str, roots: Iterable[str]) -> str | None:
    for root in roots:
        if host == root or host.endswith("." + root):
            return root
    return None


def _candidate_record(url: str, host: str, source: str) -> dict[str, Any]:
    return {
        "url": url,
        "host": host,
        "source": source,
        "discovered_at": _now(),
    }


def _intent_doc(state: Path, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer likely owner intent for every candidate without minting guessed authority."""
    reviewed = _load_json(state / "authority_reviewed_grants.json", {})
    prior_grants = list(reviewed.get("hosts", {}).values()) if isinstance(reviewed, dict) else []
    signals = _load_json(state / "human_intent_signals.json", {})
    if not isinstance(signals, dict):
        signals = {}
    supplied_links = [str(x) for x in signals.get("supplied_links", []) if isinstance(x, str)]
    owner_context = bool(signals.get("owner_context", False))
    similarity = signals.get("similarity_by_host", {})
    if not isinstance(similarity, dict):
        similarity = {}

    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        host = str(candidate.get("host", ""))
        decision = infer_human_intent(
            {
                "host": host,
                "url": candidate.get("url"),
                "method": candidate.get("method", "GET"),
                "credential_scope": candidate.get("credential_scope", "none"),
            },
            prior_explicit_approvals=prior_grants,
            supplied_links=supplied_links,
            owner_context=owner_context,
            similarity_score=float(similarity.get(host, 0.0)),
        )
        decisions.append({
            "host": host,
            "url": candidate.get("url"),
            "source": candidate.get("source"),
            **as_dict(decision),
        })

    return {
        "schema": "meta-human-intent-inference/v1",
        "generated_at": _now(),
        "policy": {
            "infer_likely_human_approval": True,
            "prior_similar_explicit_approval_is_strong_evidence": True,
            "owner_context_is_strong_evidence": True,
            "owner_supplied_link_is_strong_intent_evidence": True,
            "inference_may_prioritize_without_reprompt": True,
            "inference_may_create_new_authority": False,
            "exact_live_explicit_grant_may_be_reused_without_reprompt": True,
        },
        "decisions": decisions,
    }


def run_discovery_authorization(
    state_dir: str | Path,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Promote only discoveries that remain inside explicitly trusted roots.

    Input convention:
      meta_state/discovered_urls.json may contain URLs, href/link strings, or explicit
      host/hostname/domain fields. external_intel.json is also scanned for URL evidence.

    Output files:
      discovery_candidates.json  - every normalized discovery and decision
      discovery_authorized.json  - live probationary read-only host grants
      human_intent_decisions.json - likely-owner-intent ranking for all candidates
    """
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    roots = _trusted_roots(state)
    ttl = max(300, min(int(ttl_seconds), 24 * 60 * 60))
    now = _now()

    sources = {
        "discovered_urls": state / "discovered_urls.json",
        "external_intel": state / "external_intel.json",
    }
    candidates: list[dict[str, Any]] = []
    promoted: dict[str, dict[str, Any]] = {}

    for source_name, path in sources.items():
        payload = _load_json(path, {})
        for raw in sorted(_extract_discoveries(payload)):
            normalized = _normalize_url(raw)
            if not normalized:
                continue
            url, host = normalized
            record = _candidate_record(url, host, source_name)
            root = _within_root(host, roots)
            if root is None:
                record.update({"decision": "candidate_only", "reason": "outside_trusted_roots"})
            else:
                record.update({"decision": "probationary_authorized", "trusted_root": root})
                promoted[host] = {
                    "host": host,
                    "trusted_root": root,
                    "authorized_at": now,
                    "expires_at": now + ttl,
                    "allowed_methods": ["GET", "HEAD"],
                    "credential_scope": "none",
                    "allow_http": False,
                    "allow_delete": False,
                    "effect": "read_only",
                    "source": "meta_discovery_authorization",
                }
            candidates.append(record)

    previous = _load_json(state / "discovery_authorized.json", {})
    if isinstance(previous, dict):
        for host, grant in previous.get("hosts", {}).items():
            if not isinstance(grant, dict):
                continue
            if int(grant.get("expires_at", 0)) <= now:
                continue
            try:
                normalized_host = _normalize_host(host)
            except ValueError:
                continue
            root = _within_root(normalized_host, roots)
            if root is None:
                continue
            promoted.setdefault(normalized_host, grant)

    candidate_doc = {
        "schema": "meta-discovery-candidates/v1",
        "generated_at": now,
        "trusted_roots": sorted(roots),
        "candidates": candidates,
    }
    authorized_doc = {
        "schema": "meta-discovery-authorized/v1",
        "generated_at": now,
        "mode": "probationary_read_only",
        "hosts": dict(sorted(promoted.items())),
    }
    intent_doc = _intent_doc(state, candidates)

    (state / "discovery_candidates.json").write_text(
        json.dumps(candidate_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (state / "discovery_authorized.json").write_text(
        json.dumps(authorized_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (state / "human_intent_decisions.json").write_text(
        json.dumps(intent_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    decisions = intent_doc.get("decisions", [])
    return {
        "trusted_roots": sorted(roots),
        "candidate_count": len(candidates),
        "authorized_hosts": sorted(promoted),
        "authorized_count": len(promoted),
        "ttl_seconds": ttl,
        "intent_likely_count": sum(1 for x in decisions if x.get("likely_owner_intent")),
        "intent_auto_execute_count": sum(1 for x in decisions if x.get("may_auto_execute")),
    }
