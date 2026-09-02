"""Autonomy loop and queue management for Senju outside-world discovery.

Implements the SELECT -> DISCOVER -> FETCH -> STORE -> PASSIVE ANALYZE -> LEARN -> SELECT NEXT
research loop, using AutonomyQueue for candidate scoring and selection.

Public read-only autonomy is intentionally frictionless: GET/HEAD candidates discovered
from public HTTP(S) pages may be added to the read scope automatically. Write/effect
authority remains a separate explicit set and is never inferred from discovery.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .discovery import parse_html_evidence, PassiveObservation
from .external import ExternalContactClient, ExternalContactError, ExternalContactPolicy
from .federation import run_federation, FederationError


class AutonomyError(RuntimeError):
    """Error raised during autonomy loop execution."""


@dataclass
class HostState:
    visited_count: int = 0
    failure_count: int = 0
    last_visited_at: str | None = None
    cooldown_until: str | None = None


@dataclass
class WorkItem:
    id: str
    item_type: str  # "discovery", "passive_analysis", "canary_write", "simulation"
    url: str
    method: str = "GET"
    source: str = "direct"  # "feed", "extracted_link", "prior_contact", "api"
    score: float = 0.0
    novelty_score: float = 1.0
    expected_research_value: float = 0.5
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_host(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.hostname or "").lower().strip()


def _is_http_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


class AutonomyQueue:
    """Priority queue for discovery candidates scored by novelty and research value."""

    def __init__(self, max_host_budget: int = 5) -> None:
        self.max_host_budget = max_host_budget
        self._items: list[WorkItem] = []
        self._seen_urls: set[str] = set()
        self.host_states: dict[str, HostState] = {}

    def score_item(self, item: WorkItem) -> float:
        host = _normalize_host(item.url)
        state = self.host_states.get(host, HostState())

        # Base score from novelty and research value
        score = (item.novelty_score * 0.4) + (item.expected_research_value * 0.4)

        # Penalize prior failures and high visit counts
        score -= state.failure_count * 0.2
        score -= state.visited_count * 0.05

        # If host budget exceeded, heavily penalize
        if state.visited_count >= self.max_host_budget:
            score -= 1.0

        return max(0.0, score)

    def enqueue(self, item: WorkItem) -> bool:
        url_key = item.url.strip().rstrip("/").lower()
        if url_key in self._seen_urls:
            return False
        self._seen_urls.add(url_key)

        item.score = self.score_item(item)
        self._items.append(item)
        self._items.sort(key=lambda x: x.score, reverse=True)
        return True

    def pop_next(self) -> WorkItem | None:
        if not self._items:
            return None
        item = self._items.pop(0)
        host = _normalize_host(item.url)
        if host not in self.host_states:
            self.host_states[host] = HostState()
        return item

    def record_outcome(self, url: str, success: bool) -> None:
        host = _normalize_host(url)
        if host not in self.host_states:
            self.host_states[host] = HostState()
        state = self.host_states[host]
        state.visited_count += 1
        state.last_visited_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        if not success:
            state.failure_count += 1


class AutonomyLoop:
    """Executes live discovery plus explicitly authorized write/canary work."""

    def __init__(
        self,
        allow_hosts: Iterable[str],
        *,
        authorized_write_hosts: Iterable[str] = (),
        out_dir: str | Path = "reports/autonomy",
        client: ExternalContactClient | None = None,
        max_host_budget: int = 12,
        auto_authorize_reads: bool = True,
    ) -> None:
        self.authorized_write_hosts = frozenset(
            h.strip().lower() for h in authorized_write_hosts if h and h.strip()
        )
        self.allow_hosts: set[str] = {
            h.strip().lower() for h in allow_hosts if h and h.strip()
        } | set(self.authorized_write_hosts)
        self.auto_authorize_reads = bool(auto_authorize_reads)
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.queue = AutonomyQueue(max_host_budget=max_host_budget)
        self._client_injected = client is not None

        policy = ExternalContactPolicy.from_hosts(
            sorted(self.allow_hosts),
            allow_http=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=5.0,
            retries=1,
        )
        self.client = client or ExternalContactClient(policy)

    def _refresh_default_client(self) -> None:
        if self._client_injected:
            return
        policy = ExternalContactPolicy.from_hosts(
            sorted(self.allow_hosts),
            allow_http=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=5.0,
            retries=1,
        )
        self.client = ExternalContactClient(policy)

    def authorize_read_candidate(self, url: str) -> bool:
        """Add one public HTTP(S) hostname to the GET/HEAD research scope.

        This changes only the read scope. It never adds the host to
        ``authorized_write_hosts`` and therefore cannot turn discovery into write authority.
        DNS/public-address validation still happens in ``ExternalContactClient`` before
        network contact.
        """
        if not self.auto_authorize_reads:
            return False
        if not _is_http_url(url):
            return False
        host = _normalize_host(url)
        if not host or host in self.allow_hosts:
            return False
        self.allow_hosts.add(host)
        self._refresh_default_client()
        return True

    def is_authorized_write_target(self, url: str) -> bool:
        host = _normalize_host(url)
        return host in self.authorized_write_hosts

    def execute_step(self, item: WorkItem) -> dict[str, Any]:
        """Execute one work item through the SELECT -> DISCOVER -> FETCH -> STORE -> PASSIVE ANALYZE -> LEARN pipeline."""
        host = _normalize_host(item.url)
        if item.item_type == "canary_write":
            if not self.is_authorized_write_target(item.url):
                raise AutonomyError(
                    f"Write method {item.method} refused for unknown/unauthorized target: {host}"
                )
            return self._execute_canary_write(item)

        # Unknown/public research candidates are autonomous only for GET or HEAD.
        if item.method.upper() not in {"GET", "HEAD"}:
            raise AutonomyError(
                f"Unknown public candidate {item.url} must be GET/HEAD only, got: {item.method}"
            )
        auto_added_current = self.authorize_read_candidate(item.url)

        # 1 & 2. FETCH real HTTP content
        try:
            result = self.client.contact_with_body(item.url, method=item.method)
            self.queue.record_outcome(item.url, success=result.receipt.provider_acknowledged)
        except Exception as exc:
            self.queue.record_outcome(item.url, success=False)
            return {
                "work_item": item.to_dict(),
                "success": False,
                "auto_authorized_read_host": auto_added_current,
                "error": type(exc).__name__,
                "message": str(exc),
            }

        # 3 & 4. STORE & PASSIVE ANALYZE
        commit_sha = os.getenv("GITHUB_SHA", "local-dev-sha")
        workflow_run_id = os.getenv("GITHUB_RUN_ID", "local-run-id")
        html_text = result.text() if "html" in (result.receipt.content_type or "") or not result.receipt.content_type else ""

        headers = getattr(result, "headers", {}) or {}
        evidence = parse_html_evidence(
            requested_url=item.url,
            receipt=result.receipt,
            html_content=html_text,
            selection_score=item.score,
            discovery_source=item.source,
            commit_sha=commit_sha,
            workflow_run_id=workflow_run_id,
            headers=headers,
        )

        # Save HTML artifact if present
        if html_text:
            artifact_name = f"discovery_{result.receipt.response_sha256[:12]}.html"
            artifact_path = self.out_dir / artifact_name
            artifact_path.write_text(html_text, encoding="utf-8")
            evidence["html_artifact_path"] = str(artifact_path)

        # Save evidence artifact
        evidence_path = self.out_dir / f"evidence_{item.id}.json"
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # 5. LEARN & enqueue next candidates. Newly discovered public hosts become
        # eligible for GET/HEAD research without a human having to pre-enumerate them.
        new_enqueued = 0
        newly_authorized: list[str] = []
        for candidate in evidence.get("discovered_candidates", []):
            cand_url = candidate["url"]
            if not _is_http_url(cand_url):
                continue
            cand_host = _normalize_host(cand_url)
            if self.authorize_read_candidate(cand_url):
                newly_authorized.append(cand_host)
            if cand_host in self.allow_hosts:
                next_item = WorkItem(
                    id=f"disc-{len(self.queue._seen_urls) + 1}",
                    item_type="discovery",
                    url=cand_url,
                    method="GET",
                    source=f"link_from:{item.url}",
                    novelty_score=0.8,
                    expected_research_value=0.6,
                )
                if self.queue.enqueue(next_item):
                    new_enqueued += 1

        return {
            "work_item": item.to_dict(),
            "success": True,
            "auto_authorized_read_host": auto_added_current,
            "auto_authorized_discovered_hosts": sorted(set(newly_authorized)),
            "current_read_scope_hosts": sorted(self.allow_hosts),
            "evidence": evidence,
            "evidence_path": str(evidence_path),
            "new_enqueued_candidates": new_enqueued,
        }

    def _execute_canary_write(self, item: WorkItem) -> dict[str, Any]:
        """Reuse the Action Intents write lane with read-back verification."""
        host = _normalize_host(item.url)
        intent = {
            "schema": "senju-action-intents/v1",
            "producer": "senju-canary-writer",
            "priority": 100,
            "steps": [
                {
                    "id": "write_step",
                    "method": item.method,
                    "url": item.url,
                    "json": item.payload.get("json"),
                    "headers": item.payload.get("headers", {}),
                    "expect_status": item.payload.get("expect_status", [200, 201, 202, 204]),
                },
                {
                    "id": "readback_step",
                    "after": ["write_step"],
                    "method": "GET",
                    "url": item.payload.get("readback_url", item.url),
                    "expect_status": 200,
                },
            ],
        }

        fed_report = run_federation(
            [intent],
            allow_hosts=[host],
            max_effect="write",
            out_dir=self.out_dir / "canary_writes",
            client=self.client,
        )

        success = fed_report.get("success", False)
        self.queue.record_outcome(item.url, success=success)

        return {
            "work_item": item.to_dict(),
            "success": success,
            "federation_report": fed_report,
        }
