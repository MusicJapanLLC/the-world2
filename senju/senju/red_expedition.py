"""Autonomous RED expedition loop for explicitly authorized external hosts.

RED owns route selection, retry priority, same-authority link discovery and the
handoff into offense-first research. Authority is deliberately non-transitive:
new hosts never become authorized merely because a page links to them.

This module performs bounded HTTP observation only. It does not scan ports,
guess credentials, bypass authentication, deliver exploits, persist on targets,
or grant itself new external authority.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

from .external import (
    ContactResult,
    ExternalContactClient,
    ExternalContactError,
    ExternalContactPolicy,
)
from .offense_intel import build_bundle

SCHEMA = "senju-red-expedition/v1"
SCOPE_SCHEMA = "senju-red-expedition-scope/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_STANDARD_PATHS = ("/.well-known/security.txt", "/robots.txt", "/sitemap.xml")


class ExpeditionScopeError(ValueError):
    pass


def _host(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.hostname or "").lower().rstrip(".")


def _clean_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ExpeditionScopeError(f"unsupported expedition URL: {url}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


@dataclass(frozen=True)
class ExpeditionScope:
    scope_id: str
    allowed_hosts: frozenset[str]
    seed_urls: tuple[str, ...]
    max_contacts: int = 12
    discovery_depth: int = 2
    max_links_per_response: int = 20
    allow_http: bool = False
    retries: int = 1
    timeout_seconds: float = 6.0

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "ExpeditionScope":
        if data.get("schema") != SCOPE_SCHEMA:
            raise ExpeditionScopeError(f"scope schema must be {SCOPE_SCHEMA}")
        scope_id = str(data.get("scope_id") or "").strip()
        if not scope_id:
            raise ExpeditionScopeError("scope_id is required")
        hosts = frozenset(str(x).strip().lower().rstrip(".") for x in data.get("allowed_hosts", []) if str(x).strip())
        if not hosts:
            raise ExpeditionScopeError("allowed_hosts must not be empty")
        seeds = tuple(_clean_url(str(x)) for x in data.get("seed_urls", []) if str(x).strip())
        if not seeds:
            raise ExpeditionScopeError("seed_urls must not be empty")
        for seed in seeds:
            if _host(seed) not in hosts:
                raise ExpeditionScopeError(f"seed host is outside allowed_hosts: {_host(seed)}")
        max_contacts = int(data.get("max_contacts", 12))
        discovery_depth = int(data.get("discovery_depth", 2))
        max_links = int(data.get("max_links_per_response", 20))
        if not 1 <= max_contacts <= 40:
            raise ExpeditionScopeError("max_contacts must be 1..40")
        if not 0 <= discovery_depth <= 3:
            raise ExpeditionScopeError("discovery_depth must be 0..3")
        if not 1 <= max_links <= 50:
            raise ExpeditionScopeError("max_links_per_response must be 1..50")
        return ExpeditionScope(
            scope_id=scope_id,
            allowed_hosts=hosts,
            seed_urls=seeds,
            max_contacts=max_contacts,
            discovery_depth=discovery_depth,
            max_links_per_response=max_links,
            allow_http=bool(data.get("allow_http", False)),
            retries=max(0, min(int(data.get("retries", 1)), 3)),
            timeout_seconds=max(1.0, min(float(data.get("timeout_seconds", 6.0)), 15.0)),
        )

    @staticmethod
    def from_file(path: str | Path) -> "ExpeditionScope":
        return ExpeditionScope.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))

    def policy(self) -> ExternalContactPolicy:
        return ExternalContactPolicy(
            allow_hosts=self.allowed_hosts,
            allow_http=self.allow_http,
            allowed_methods=SAFE_METHODS,
            allow_delete=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=self.timeout_seconds,
            max_request_bytes=1024,
            max_response_bytes=512 * 1024,
            retries=self.retries,
            retry_backoff_seconds=0.25,
        )


@dataclass
class RouteMemory:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    last_status: int | None = None
    discovered_links: int = 0


@dataclass
class ExpeditionMemory:
    routes: dict[str, RouteMemory] = field(default_factory=dict)

    def state(self, url: str) -> RouteMemory:
        return self.routes.setdefault(url, RouteMemory())

    def score(self, url: str, depth: int) -> float:
        state = self.state(url)
        score = 3.0 if state.attempts == 0 else 0.6
        score += min(2.0, state.failures * 0.45)  # failure-revenge / route re-check
        score += min(1.0, state.discovered_links * 0.08)
        if state.last_status is not None and 500 <= state.last_status:
            score += 0.8
        if state.last_status in {401, 403}:
            score += 0.25
        score -= depth * 0.18
        score -= state.successes * 0.12
        return round(score, 4)

    def record(self, url: str, *, status: int | None, success: bool, discovered_links: int = 0) -> None:
        state = self.state(url)
        state.attempts += 1
        state.successes += int(success)
        state.failures += int(not success)
        state.last_status = status
        state.discovered_links += max(0, int(discovered_links))

    def to_dict(self) -> dict[str, Any]:
        return {url: asdict(state) for url, state in sorted(self.routes.items())}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "link"}:
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def extract_allowed_links(base_url: str, body: bytes, allowed_hosts: frozenset[str], *, limit: int) -> list[str]:
    parser = _LinkParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    out: list[str] = []
    for raw in parser.links:
        absolute = urllib.parse.urljoin(base_url, raw)
        try:
            clean = _clean_url(absolute)
        except ExpeditionScopeError:
            continue
        if _host(clean) not in allowed_hosts:
            continue
        if clean not in out:
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def _standard_routes(seed: str, allowed_hosts: frozenset[str]) -> list[str]:
    parsed = urllib.parse.urlsplit(seed)
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    routes = [seed]
    for path in _STANDARD_PATHS:
        candidate = urllib.parse.urljoin(origin, path)
        if _host(candidate) in allowed_hosts and candidate not in routes:
            routes.append(candidate)
    return routes


def _finding_report(scope: ExpeditionScope, observations: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(severity: str, key: str, title: str, evidence: str) -> None:
        marker = f"{key}:{evidence}"
        if marker in seen:
            return
        seen.add(marker)
        findings.append({
            "severity": severity,
            "key": key,
            "title": title,
            "evidence": evidence[:240],
            "remediation": "Feed this measured signal into RED research before BLUE remediation prioritization.",
        })

    for item in observations:
        if not item.get("success"):
            continue
        status = int(item.get("status") or 0)
        headers = {str(k).lower(): str(v) for k, v in (item.get("headers") or {}).items()}
        ctype = headers.get("content-type", "")
        if status >= 500:
            add("medium", "external-5xx", "Observed server-side 5xx surface", f"{item['url']} returned {status}")
        if "text/html" in ctype and "content-security-policy" not in headers:
            add("medium", "csp-missing", "HTML response lacks CSP", item["url"])
        if "server" in headers:
            add("low", "banner-server", "Server technology banner observed", headers["server"])
        allow = {x.strip().upper() for x in headers.get("allow", "").split(",") if x.strip()}
        if allow & {"TRACE", "PUT", "DELETE", "PATCH", "CONNECT"}:
            add("medium", "dangerous-methods-advertised", "Potentially dangerous HTTP methods advertised", ", ".join(sorted(allow)))

    return {
        "schema": "senju-authorized-pentest-report/v1",
        "scope_id": scope.scope_id,
        "target": scope.seed_urls[0],
        "started_at_utc": "expedition-derived",
        "completed_at_utc": "expedition-derived",
        "requests_used": len(observations),
        "findings": findings,
        "receipts": [],
        "boundaries": {
            "credential_guessing": False,
            "auth_bypass": False,
            "exploit_delivery": False,
            "persistence": False,
            "destructive_requests": False,
            "lateral_movement": False,
            "methods": sorted(SAFE_METHODS),
        },
    }


def run_expedition(
    scope: ExpeditionScope,
    *,
    cycles: int = 10,
    seed: int = 20260831,
    client: ExternalContactClient | None = None,
) -> dict[str, Any]:
    """Let RED autonomously choose and contact routes inside an existing authority scope."""
    transport = client or ExternalContactClient(scope.policy())
    memory = ExpeditionMemory()
    frontier: dict[str, int] = {}
    for seed_url in scope.seed_urls:
        for route in _standard_routes(seed_url, scope.allowed_hosts):
            frontier.setdefault(route, 0)

    observations: list[dict[str, Any]] = []
    contacted: set[str] = set()

    while frontier and len(observations) < scope.max_contacts:
        ranked = sorted(frontier.items(), key=lambda row: (-memory.score(row[0], row[1]), row[1], row[0]))
        url, depth = ranked[0]
        frontier.pop(url, None)
        method = "GET" if memory.state(url).attempts == 0 else "HEAD"
        try:
            result: ContactResult = transport.contact_with_body(url, method=method, headers={"Accept": "text/html,application/json,text/plain,*/*"})
            receipt = result.receipt
            headers = {}
            # ContactReceipt intentionally stores a curated subset; the body is enough for discovery.
            content_type = receipt.content_type or ""
            if content_type:
                headers["content-type"] = content_type
            success = 200 <= receipt.status < 500
            links: list[str] = []
            if method == "GET" and depth < scope.discovery_depth and "text/html" in content_type.lower():
                links = extract_allowed_links(url, result.body, scope.allowed_hosts, limit=scope.max_links_per_response)
                for link in links:
                    if link not in contacted and link not in frontier:
                        frontier[link] = depth + 1
            memory.record(url, status=receipt.status, success=success, discovered_links=len(links))
            observations.append({
                "url": url,
                "method": method,
                "depth": depth,
                "success": success,
                "status": receipt.status,
                "final_url": receipt.final_url,
                "contacted_hosts": list(receipt.contacted_hosts),
                "resolved_ips": list(receipt.resolved_ips),
                "response_bytes": receipt.response_bytes,
                "response_sha256": receipt.response_sha256,
                "headers": headers,
                "discovered_links": links,
            })
            contacted.add(url)
        except ExternalContactError as exc:
            memory.record(url, status=None, success=False)
            observations.append({
                "url": url,
                "method": method,
                "depth": depth,
                "success": False,
                "status": None,
                "error": str(exc),
                "discovered_links": [],
            })
            contacted.add(url)

    measured = _finding_report(scope, observations)
    red_bundle = build_bundle([measured], cycles=max(1, min(int(cycles), 24)), seed=seed, max_steps=6)
    return {
        "schema": SCHEMA,
        "doctrine": "RED_SELF_DIRECTED_AUTHORIZED_EXPEDITION",
        "scope_id": scope.scope_id,
        "network_io": True,
        "autonomous_route_selection": True,
        "autonomous_retry_priority": True,
        "autonomous_same_authority_discovery": True,
        "authority_self_expansion": False,
        "credential_guessing": False,
        "auth_bypass_execution": False,
        "exploit_delivery": False,
        "destructive_requests": False,
        "allowed_hosts": sorted(scope.allowed_hosts),
        "contacts": observations,
        "contact_count": len(observations),
        "discovered_route_count": sum(len(x.get("discovered_links") or []) for x in observations),
        "memory": memory.to_dict(),
        "red_handoff": red_bundle,
        "priority_next": red_bundle.get("priority_next", []),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run autonomous RED expedition inside an explicit external authority scope")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260831)
    args = parser.parse_args(argv)
    scope = ExpeditionScope.from_file(args.scope)
    report = run_expedition(scope, cycles=args.cycles, seed=args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "SENJU_RED_EXPEDITION_VERIFIED "
        f"scope={scope.scope_id} contacts={report['contact_count']} priorities={','.join(report['priority_next'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
