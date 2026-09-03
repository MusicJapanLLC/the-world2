"""Closed-loop discovery authorization and live read-only crawling.

Production flow:

    AI discovery / crawler log / external response
      -> shared discovery event knowledge
      -> inherited owner-scope authorization
      -> real credential-free HTTPS GET probe
      -> bounded link extraction
      -> newly discovered URLs back to shared knowledge
      -> authorization re-evaluation in the same run

Discovery alone never creates a new unrelated authority root. The live crawler executes
only scan/probe on URLs whose exact host carries a still-live read-only discovery grant.
Higher impact actions may exist in the separate action queue only when backed by an
explicit exact-host owner profile; this crawler never executes them.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .discovery_authorization import URL_RE, _load_json, _normalize_host, _normalize_url
from .discovery_event_bus import (
    load_discovery_events,
    materialize_discovery_events,
    publish_discovery_event,
)
from .shared_discovery_authority import run_shared_discovery_authority

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SENJU_ROOT = _REPO_ROOT / "senju"
if str(_SENJU_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENJU_ROOT))

from senju.external import ExternalContactClient, ExternalContactError, ExternalContactPolicy  # noqa: E402

CLOSED_LOOP_SCHEMA = "meta-discovery-authority-closed-loop/v1"
MAX_ROUNDS = 5
MAX_TARGETS_PER_ROUND = 50
MAX_LINKS_PER_RESPONSE = 200
MAX_RESPONSE_BYTES = 128 * 1024


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() in {"href", "src", "action"} and value:
                self.values.append(value)


def _now() -> int:
    return int(time.time())


def _known_urls(state: Path) -> set[str]:
    known = {str(row.get("url", "")) for row in load_discovery_events(state)}
    shared = _load_json(state / "shared_discovery_knowledge.json", {})
    if isinstance(shared, dict):
        for row in shared.get("discoveries", []):
            if isinstance(row, dict) and isinstance(row.get("url"), str):
                known.add(str(row["url"]))
    return {url for url in known if url}


def extract_response_urls(base_url: str, body: bytes, *, limit: int = MAX_LINKS_PER_RESPONSE) -> tuple[str, ...]:
    """Extract normalized HTTPS absolute/relative links from a bounded response body."""
    bounded = bytes(body[:MAX_RESPONSE_BYTES])
    text = bounded.decode("utf-8", errors="replace")
    candidates: set[str] = set(URL_RE.findall(text))

    parser = _LinkParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    for value in parser.values:
        try:
            candidates.add(urllib.parse.urljoin(base_url, value))
        except ValueError:
            continue

    normalized: set[str] = set()
    for raw in candidates:
        item = _normalize_url(raw)
        if item is None:
            continue
        url, _ = item
        normalized.add(url)
        if len(normalized) >= max(1, min(int(limit), MAX_LINKS_PER_RESPONSE)):
            break
    return tuple(sorted(normalized))


def _live_read_only_grant(state: Path, host: str, *, now: int) -> dict[str, Any] | None:
    authorized = _load_json(state / "discovery_authorized.json", {})
    hosts = authorized.get("hosts", {}) if isinstance(authorized, dict) else {}
    grant = hosts.get(host) if isinstance(hosts, dict) else None
    if not isinstance(grant, dict):
        return None
    if int(grant.get("expires_at", 0)) <= now:
        return None
    if str(grant.get("credential_scope", "none")).strip().lower() != "none":
        return None
    if str(grant.get("effect", "read_only")).strip().lower() != "read_only":
        return None
    methods = {str(item).strip().upper() for item in grant.get("allowed_methods", [])}
    if "GET" not in methods:
        return None
    return grant


def _authorized_url_candidates(state: Path, *, now: int) -> tuple[dict[str, Any], ...]:
    """Return exact URLs that may be probed under a live inherited read-only host grant.

    Host-root actions remain the canonical execution queue. In addition, every URL in
    shared discovery knowledge whose decision is probationary_authorized becomes a
    URL-granular scan/probe candidate. This makes a discovered internal path operational
    without broadening the host authority that justified it.
    """
    candidates: list[dict[str, Any]] = []

    queue = _load_json(state / "discovery_action_queue.json", {})
    rows = queue.get("actions", []) if isinstance(queue, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != "ready":
                continue
            capabilities = {str(item).strip().lower() for item in row.get("capabilities", [])}
            if not capabilities.intersection({"scan", "probe"}):
                continue
            raw_host = str(row.get("target", "")).strip()
            raw_url = str(row.get("url", "")).strip()
            try:
                host = _normalize_host(raw_host)
            except ValueError:
                continue
            normalized = _normalize_url(raw_url)
            if normalized is None:
                continue
            url, url_host = normalized
            if url_host != host:
                continue
            grant = _live_read_only_grant(state, host, now=now)
            if grant is None:
                continue
            candidates.append(
                {
                    "host": host,
                    "url": url,
                    "authorization_reference": row.get("authorization_reference") or host,
                    "candidate_source": "action_queue",
                }
            )

    shared = _load_json(state / "shared_discovery_knowledge.json", {})
    discoveries = shared.get("discoveries", []) if isinstance(shared, dict) else []
    if isinstance(discoveries, list):
        for row in discoveries:
            if not isinstance(row, dict) or row.get("decision") != "probationary_authorized":
                continue
            normalized = _normalize_url(str(row.get("url", "")))
            if normalized is None:
                continue
            url, host = normalized
            grant = _live_read_only_grant(state, host, now=now)
            if grant is None:
                continue
            candidates.append(
                {
                    "host": host,
                    "url": url,
                    "authorization_reference": (
                        grant.get("authorization_reference")
                        or row.get("authorization_reference")
                        or host
                    ),
                    "candidate_source": "shared_discovery_url",
                }
            )

    # Queue candidates win ties because they carry the canonical action record. Shared
    # URLs add path-level coverage beyond the one host-root queue entry.
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique.setdefault(str(candidate["url"]), candidate)
    return tuple(unique.values())


def run_authorized_discovery_crawl(
    state_dir: str | Path,
    *,
    max_targets: int = 20,
    seen_targets: set[str] | None = None,
    client_factory: Callable[[ExternalContactPolicy], Any] | None = None,
) -> dict[str, Any]:
    """GET authorized discovered URLs and feed newly found links back to the bus."""
    state = Path(state_dir)
    seen = seen_targets if seen_targets is not None else set()
    known = _known_urls(state)
    limit = max(1, min(int(max_targets), MAX_TARGETS_PER_ROUND))
    attempted = 0
    succeeded = 0
    failed = 0
    new_events = 0
    receipts: list[dict[str, Any]] = []
    now = _now()
    candidates = _authorized_url_candidates(state, now=now)

    for row in candidates:
        if attempted >= limit:
            break
        host = str(row["host"])
        url = str(row["url"])
        if url in seen:
            continue
        # Re-check immediately before every network action so expiry/revocation-like
        # removal from the runtime grant takes effect within the same loop.
        grant = _live_read_only_grant(state, host, now=_now())
        if grant is None:
            continue

        seen.add(url)
        attempted += 1
        started = time.monotonic()
        policy = ExternalContactPolicy.from_hosts(
            [host],
            allow_http=False,
            allow_delete=False,
            follow_redirects=False,
            timeout_seconds=6.0,
            max_response_bytes=MAX_RESPONSE_BYTES,
            retries=0,
        )
        client = client_factory(policy) if client_factory is not None else ExternalContactClient(policy)
        try:
            result = client.contact_with_body(url, method="GET")
            succeeded += 1
            discovered = extract_response_urls(url, result.body)
            published: list[str] = []
            for found in discovered:
                if found in known:
                    continue
                try:
                    event = publish_discovery_event(
                        state,
                        actor="X/PROBE",
                        url=found,
                        source=f"authorized_response:{host}",
                        metadata={
                            "parent_url": url,
                            "http_status": int(result.receipt.status),
                            "authorization_reference": row.get("authorization_reference"),
                        },
                    )
                except ValueError:
                    continue
                known.add(str(event["url"]))
                published.append(str(event["url"]))
            new_events += len(published)
            receipts.append(
                {
                    "host": host,
                    "url": url,
                    "status": "success",
                    "http_status": int(result.receipt.status),
                    "final_url": str(result.receipt.final_url),
                    "resolved_ips": list(result.receipt.resolved_ips),
                    "response_bytes": len(result.body),
                    "new_discoveries": published,
                    "new_discovery_count": len(published),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "authorization_reference": row.get("authorization_reference"),
                    "candidate_source": row.get("candidate_source"),
                    "executed_capability": "scan_probe",
                    "credential_scope": "none",
                }
            )
        except (ExternalContactError, OSError, TimeoutError) as exc:
            failed += 1
            receipts.append(
                {
                    "host": host,
                    "url": url,
                    "status": "failed",
                    "error": str(exc)[:300],
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "authorization_reference": row.get("authorization_reference"),
                    "candidate_source": row.get("candidate_source"),
                    "executed_capability": "scan_probe",
                    "credential_scope": "none",
                }
            )

    remaining = sum(1 for candidate in candidates if str(candidate["url"]) not in seen)
    return {
        "candidate_count": len(candidates),
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "new_event_count": new_events,
        "remaining_candidate_count": remaining,
        "receipts": receipts,
    }


def run_discovery_closed_loop(
    state_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
    max_rounds: int = 3,
    max_targets_per_round: int = 20,
    client_factory: Callable[[ExternalContactPolicy], Any] | None = None,
) -> dict[str, Any]:
    """Run Discovery -> Authorize -> URL Probe -> Rediscover until stable or bounded."""
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    rounds_limit = max(1, min(int(max_rounds), MAX_ROUNDS))
    seen_targets: set[str] = set()
    round_receipts: list[dict[str, Any]] = []
    total_new_events = 0
    final_shared: dict[str, Any] = {}

    for round_no in range(1, rounds_limit + 1):
        materialize_before = materialize_discovery_events(state)
        before = run_shared_discovery_authority(state, repo_root=repo_root)
        crawl = run_authorized_discovery_crawl(
            state,
            max_targets=max_targets_per_round,
            seen_targets=seen_targets,
            client_factory=client_factory,
        )
        materialize_after = materialize_discovery_events(state)
        after = run_shared_discovery_authority(state, repo_root=repo_root)
        final_shared = after
        total_new_events += int(crawl.get("new_event_count", 0))
        round_receipts.append(
            {
                "round": round_no,
                "materialized_event_count_before": materialize_before["event_count"],
                "authorized_before": before.get("authorized_count", 0),
                "action_ready_before": before.get("action_ready_count", 0),
                "crawl": crawl,
                "materialized_event_count_after": materialize_after["event_count"],
                "authorized_after": after.get("authorized_count", 0),
                "action_ready_after": after.get("action_ready_count", 0),
            }
        )
        if (
            int(crawl.get("new_event_count", 0)) == 0
            and int(crawl.get("remaining_candidate_count", 0)) == 0
        ):
            break

    payload = {
        "schema": CLOSED_LOOP_SCHEMA,
        "generated_at": _now(),
        "mode": "live_read_only_discovery_authority_closed_loop",
        "rounds_completed": len(round_receipts),
        "new_event_count": total_new_events,
        "seen_target_count": len(seen_targets),
        "final_shared_discovery_count": int(final_shared.get("shared_discovery_count", 0)),
        "final_authorized_count": int(final_shared.get("authorized_count", 0)),
        "final_action_ready_count": int(final_shared.get("action_ready_count", 0)),
        "final_high_impact_ready_count": int(final_shared.get("high_impact_ready_count", 0)),
        "rounds": round_receipts,
    }
    # Avoid discovery/crawl/link/log tokens in the filename so source ingestion cannot
    # recursively ingest its own execution receipts.
    (state / "loop_receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload
