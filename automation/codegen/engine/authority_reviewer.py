"""Independent reviewer for META discovery candidates.

The discovery component may propose URLs/hosts, but it cannot grant arbitrary new
network authority by itself. This reviewer runs as a separate decision stage and only
issues short-lived, read-only grants when the candidate is independently covered by an
explicit owner-authorized root already present in canonical repository configuration.

Important properties:
- source-page links are evidence of discovery, not authority by themselves;
- unrelated third-party hosts remain pending/rejected;
- approvals are HTTPS-only, GET/HEAD-only, credential-free, and expire;
- redirect targets may consume these grants, but still require per-hop validation.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TTL_SECONDS = 6 * 60 * 60


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _normalize_host(value: str) -> str | None:
    try:
        host = value.strip().rstrip(".").lower().encode("idna").decode("ascii")
    except (AttributeError, UnicodeError):
        return None
    if not host or any(ch in host for ch in "/?#@") or "." not in host:
        return None
    return host


def _host_from_url(value: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
        return None
    if not parsed.hostname:
        return None
    try:
        if parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    return _normalize_host(parsed.hostname)


def _explicit_roots(repo_root: Path) -> set[str]:
    """Collect only explicit roots/targets; never inherit arbitrary href destinations."""
    roots: set[str] = set()

    canonical = _load_json(repo_root / "AUTHORIZED_TEST_TARGETS.json", {})
    if isinstance(canonical, dict):
        for target in canonical.get("targets", []):
            if not isinstance(target, dict):
                continue
            if target.get("owner_authorization") != "explicit":
                continue
            for key in ("host", "base_url"):
                raw = target.get(key)
                if not isinstance(raw, str):
                    continue
                host = _host_from_url(raw) if key == "base_url" else _normalize_host(raw)
                if host:
                    roots.add(host)

    federation = _load_json(repo_root / "senju" / "config" / "authorized-test-federation.json", {})
    if isinstance(federation, dict):
        for raw in federation.get("domain_roots", []):
            if isinstance(raw, str):
                host = _normalize_host(raw)
                if host:
                    roots.add(host)

    discovery_policy = _load_json(
        repo_root / "automation" / "codegen" / "meta_state" / "discovery_policy.json", {}
    )
    if isinstance(discovery_policy, dict):
        for raw in discovery_policy.get("trusted_roots", []):
            if isinstance(raw, str):
                host = _normalize_host(raw)
                if host:
                    roots.add(host)

    return roots


def _covered_by_root(host: str, roots: Iterable[str]) -> str | None:
    for root in roots:
        if host == root or host.endswith("." + root):
            return root
    return None


def run_authority_review(
    state_dir: str | Path,
    *,
    repo_root: str | Path = ROOT,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Review discovery candidates and issue independent short-lived grants."""
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    ttl = max(300, min(int(ttl_seconds), 24 * 60 * 60))

    candidate_doc = _load_json(state / "discovery_candidates.json", {})
    candidates = candidate_doc.get("candidates", []) if isinstance(candidate_doc, dict) else []
    explicit_roots = _explicit_roots(root)

    decisions: list[dict[str, Any]] = []
    grants: dict[str, dict[str, Any]] = {}

    for item in candidates:
        if not isinstance(item, dict):
            continue
        host = _normalize_host(str(item.get("host", "")))
        url = str(item.get("url", ""))
        if not host or _host_from_url(url) != host:
            decisions.append({
                "host": item.get("host"),
                "url": url,
                "decision": "reject",
                "reason": "invalid_https_candidate",
            })
            continue

        matched_root = _covered_by_root(host, explicit_roots)
        if matched_root is None:
            decisions.append({
                "host": host,
                "url": url,
                "decision": "hold",
                "reason": "no_independent_explicit_authority",
            })
            continue

        grant = {
            "host": host,
            "matched_explicit_root": matched_root,
            "reviewer": "senju-authority-reviewer/v1",
            "reviewed_at": now,
            "expires_at": now + ttl,
            "allowed_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "effect": "read_only",
            "allow_http": False,
            "allow_delete": False,
            "redirect_eligible": True,
        }
        grants[host] = grant
        decisions.append({
            "host": host,
            "url": url,
            "decision": "approve_probationary",
            "matched_explicit_root": matched_root,
        })

    previous = _load_json(state / "authority_reviewed_grants.json", {})
    if isinstance(previous, dict):
        for host, grant in previous.get("hosts", {}).items():
            if not isinstance(grant, dict) or int(grant.get("expires_at", 0)) <= now:
                continue
            normalized = _normalize_host(host)
            if not normalized:
                continue
            matched = _covered_by_root(normalized, explicit_roots)
            if matched:
                grants.setdefault(normalized, grant)

    review_doc = {
        "schema": "meta-authority-review/v1",
        "reviewer": "senju-authority-reviewer/v1",
        "generated_at": now,
        "explicit_roots": sorted(explicit_roots),
        "decisions": decisions,
    }
    grant_doc = {
        "schema": "meta-authority-reviewed-grants/v1",
        "generated_at": now,
        "mode": "independent_probationary_read_only",
        "hosts": dict(sorted(grants.items())),
    }
    (state / "authority_review.json").write_text(
        json.dumps(review_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (state / "authority_reviewed_grants.json").write_text(
        json.dumps(grant_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "reviewed_count": len(decisions),
        "approved_count": len(grants),
        "approved_hosts": sorted(grants),
        "explicit_roots": sorted(explicit_roots),
        "ttl_seconds": ttl,
    }
