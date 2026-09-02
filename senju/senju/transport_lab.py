"""Guarded multi-route transport experimentation for Senju/META.

This module deliberately does *not* create a guard-bypass channel.  Every route is a
strategy layered on top of ExternalContactClient, so the same explicit host authority,
public-DNS validation, redirect re-validation, HTTPS defaults, method bounds, and
sensitive-header handling remain mandatory.

The lab gives META/Senju the useful part of route experimentation:
- several bounded transport strategies;
- automatic fallback when one strategy fails;
- simple success/failure scoring across rounds;
- short, auditable experiment receipts;
- targets restricted to live, non-expired authority-review grants.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .external import ExternalContactClient, ExternalContactError, ExternalContactPolicy


@dataclass(frozen=True)
class TransportLane:
    name: str
    method: str = "GET"
    timeout_seconds: float = 5.0
    retries: int = 1
    follow_redirects: bool = True
    max_redirects: int = 2


DEFAULT_LANES: tuple[TransportLane, ...] = (
    TransportLane(
        name="head_probe",
        method="HEAD",
        timeout_seconds=3.0,
        retries=0,
        follow_redirects=True,
        max_redirects=2,
    ),
    TransportLane(
        name="fast_get",
        method="GET",
        timeout_seconds=4.0,
        retries=0,
        follow_redirects=True,
        max_redirects=2,
    ),
    TransportLane(
        name="resilient_get",
        method="GET",
        timeout_seconds=8.0,
        retries=2,
        follow_redirects=True,
        max_redirects=3,
    ),
    TransportLane(
        name="direct_get_no_redirect",
        method="GET",
        timeout_seconds=5.0,
        retries=1,
        follow_redirects=False,
        max_redirects=0,
    ),
)


@dataclass
class LaneScore:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    score: float = 0.0
    last_status: int | None = None
    last_error: str | None = None

    def record_success(self, status: int) -> None:
        self.attempts += 1
        self.successes += 1
        self.score += 2.0
        self.last_status = int(status)
        self.last_error = None

    def record_failure(self, error: Exception) -> None:
        self.attempts += 1
        self.failures += 1
        self.score -= 1.0
        self.last_error = str(error)[:240]


@dataclass(frozen=True)
class ReviewedAuthority:
    hosts: frozenset[str]
    expires_at: dict[str, int]

    def allows(self, host: str, *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        return host in self.hosts and int(self.expires_at.get(host, 0)) > now


def _normalize_host(raw: str) -> str:
    value = raw.strip().rstrip(".").lower()
    if not value or any(ch in value for ch in "/?#@"):
        raise ValueError("invalid host")
    return value.encode("idna").decode("ascii")


def load_reviewed_authority(path: str | Path, *, now: int | None = None) -> ReviewedAuthority:
    """Load only live, read-only grants produced by the independent reviewer."""
    now = int(time.time()) if now is None else int(now)
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        doc = {}

    hosts: set[str] = set()
    expires: dict[str, int] = {}
    for raw_host, grant in doc.get("hosts", {}).items() if isinstance(doc, dict) else []:
        if not isinstance(grant, dict):
            continue
        try:
            host = _normalize_host(str(raw_host))
            expiry = int(grant.get("expires_at", 0))
        except (ValueError, TypeError):
            continue
        methods = {str(m).upper() for m in grant.get("allowed_methods", [])}
        if expiry <= now:
            continue
        if not {"GET", "HEAD"}.intersection(methods):
            continue
        if grant.get("credential_scope", "none") != "none":
            continue
        if grant.get("allow_http", False):
            continue
        if grant.get("allow_delete", False):
            continue
        hosts.add(host)
        expires[host] = expiry
    return ReviewedAuthority(frozenset(hosts), expires)


def validate_target_url(url: str, authority: ReviewedAuthority, *, now: int | None = None) -> str:
    """Return normalized host or fail closed before any route is attempted."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ExternalContactError("transport lab requires HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ExternalContactError("credentials in target URL are not allowed")
    if not parsed.hostname:
        raise ExternalContactError("target URL has no hostname")
    try:
        if parsed.port not in (None, 443):
            raise ExternalContactError("non-default target port is not authorized")
    except ValueError as exc:
        raise ExternalContactError("invalid target port") from exc
    host = _normalize_host(parsed.hostname)
    if not authority.allows(host, now=now):
        raise ExternalContactError(f"target lacks a live reviewed authority grant: {host}")
    return host


def _policy_for_lane(authority: ReviewedAuthority, lane: TransportLane) -> ExternalContactPolicy:
    # All reviewed hosts are supplied so a redirect may proceed only when its destination
    # already has a separate, still-live reviewed grant. ExternalContactClient re-validates
    # every hop against this exact set.
    return ExternalContactPolicy.from_hosts(
        authority.hosts,
        allow_http=False,
        allow_delete=False,
        follow_redirects=lane.follow_redirects,
        max_redirects=lane.max_redirects,
        timeout_seconds=lane.timeout_seconds,
        retries=lane.retries,
    )


def _lane_order(lanes: Iterable[TransportLane], scores: dict[str, LaneScore]) -> list[TransportLane]:
    # Stable tie-break preserves the declared lane order until evidence accumulates.
    indexed = list(enumerate(lanes))
    indexed.sort(key=lambda pair: (-scores[pair[1].name].score, pair[0]))
    return [lane for _, lane in indexed]


def run_transport_loop(
    url: str,
    authority: ReviewedAuthority,
    *,
    rounds: int = 3,
    lanes: Iterable[TransportLane] = DEFAULT_LANES,
    client_factory: Callable[[ExternalContactPolicy, TransportLane], ExternalContactClient] | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Try bounded guarded strategies, learn scores, and fall back automatically.

    At most one successful lane is used per round.  A round may try each lane once if
    prior lanes fail.  The number of rounds is hard-bounded to prevent runaway traffic.
    """
    host = validate_target_url(url, authority)
    lane_list = tuple(lanes)
    if not lane_list:
        raise ValueError("at least one transport lane is required")
    if len({lane.name for lane in lane_list}) != len(lane_list):
        raise ValueError("transport lane names must be unique")
    bounded_rounds = max(1, min(int(rounds), 10))
    scores = {lane.name: LaneScore() for lane in lane_list}
    events: list[dict[str, Any]] = []

    for round_no in range(1, bounded_rounds + 1):
        round_succeeded = False
        for lane in _lane_order(lane_list, scores):
            # Re-check the target's grant before every attempt so a grant that expires
            # mid-loop cannot be reused for a later round/lane.
            validate_target_url(url, authority)
            policy = _policy_for_lane(authority, lane)
            client = (
                client_factory(policy, lane)
                if client_factory is not None
                else ExternalContactClient(policy)
            )
            started = time.monotonic()
            try:
                result = client.contact_with_body(url, method=lane.method)
                elapsed_ms = round((time.monotonic() - started) * 1000, 2)
                scores[lane.name].record_success(result.receipt.status)
                events.append({
                    "round": round_no,
                    "lane": lane.name,
                    "outcome": "success",
                    "status": result.receipt.status,
                    "elapsed_ms": elapsed_ms,
                    "final_host": result.receipt.final_host,
                    "redirect_count": result.receipt.redirect_count,
                })
                round_succeeded = True
                break
            except (ExternalContactError, OSError, TimeoutError) as exc:
                elapsed_ms = round((time.monotonic() - started) * 1000, 2)
                scores[lane.name].record_failure(exc)
                events.append({
                    "round": round_no,
                    "lane": lane.name,
                    "outcome": "failure",
                    "error": str(exc)[:240],
                    "elapsed_ms": elapsed_ms,
                })
        if not round_succeeded:
            events.append({
                "round": round_no,
                "lane": None,
                "outcome": "round_exhausted",
            })

    winner = max(
        lane_list,
        key=lambda lane: (scores[lane.name].score, scores[lane.name].successes, -scores[lane.name].failures),
    )
    result_doc: dict[str, Any] = {
        "schema": "senju-guarded-transport-lab/v1",
        "target_url": url,
        "target_host": host,
        "rounds": bounded_rounds,
        "winner": winner.name,
        "scores": {name: asdict(score) for name, score in scores.items()},
        "events": events,
        "authority_hosts": sorted(authority.hosts),
        "guard_bypass": False,
    }
    if state_path is not None:
        output = Path(state_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result_doc
