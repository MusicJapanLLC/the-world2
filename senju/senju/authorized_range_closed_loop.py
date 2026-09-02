"""Adaptive closed-loop assessment for an explicitly authorized Senju range.

The loop is intentionally bounded to one exact HTTPS host.  It diversifies
low-impact probes, crawls only same-origin links, deduplicates findings, learns
which probe families are producing useful signal, and emits machine-readable
sharing records for other Senju agents.

This module does not implement credential attacks, brute force, destructive
writes, persistence, exploit payloads, or host expansion.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import math
import time
import urllib.parse
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .external import ExternalContactClient, ExternalContactPolicy


class AuthorizedRangeLoopError(RuntimeError):
    """Raised when a closed-loop run would leave its explicit authority."""


@dataclass(frozen=True)
class AuthorizedRangePolicy:
    scope_id: str
    host: str
    max_rps: float = 5.0
    timeout_seconds: float = 15.0
    max_response_bytes: int = 8 * 1024 * 1024
    retries: int = 2
    follow_redirects: bool = True
    max_redirects: int = 4
    recursive_same_origin: bool = True

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AuthorizedRangePolicy":
        roots = raw.get("domain_roots", [])
        if not isinstance(roots, list) or len(roots) != 1 or not isinstance(roots[0], str):
            raise AuthorizedRangeLoopError("closed loop requires exactly one domain root")
        host = roots[0].strip().rstrip(".").lower()
        if not host or any(ch in host for ch in "/*?#@"):
            raise AuthorizedRangeLoopError("domain root must be one exact hostname")
        if raw.get("allow_http", False):
            raise AuthorizedRangeLoopError("authorized-range closed loop is HTTPS-only")
        max_rps = float(raw.get("max_rps", 5.0))
        if not math.isfinite(max_rps) or not 0.1 <= max_rps <= 10.0:
            raise AuthorizedRangeLoopError("max_rps must be between 0.1 and 10")
        return cls(
            scope_id=str(raw.get("scope_id", "authorized-range")).strip() or "authorized-range",
            host=host,
            max_rps=max_rps,
            timeout_seconds=max(0.5, min(float(raw.get("timeout_seconds", 15.0)), 20.0)),
            max_response_bytes=max(1024, min(int(raw.get("max_response_bytes", 8 * 1024 * 1024)), 10 * 1024 * 1024)),
            retries=max(0, min(int(raw.get("retries", 2)), 5)),
            follow_redirects=bool(raw.get("follow_redirects", True)),
            max_redirects=max(0, min(int(raw.get("max_redirects", 4)), 5)),
            recursive_same_origin=bool(raw.get("recursive_same_origin", True)),
        )

    @classmethod
    def load(cls, path: str | Path) -> "AuthorizedRangePolicy":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise AuthorizedRangeLoopError("range config must be a JSON object")
        return cls.from_dict(raw)

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    def normalize_url(self, value: str, *, base: str | None = None) -> str | None:
        absolute = urllib.parse.urljoin(base or f"{self.origin}/", value)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme.lower() != "https" or (parsed.hostname or "").rstrip(".").lower() != self.host:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.port not in {None, 443}:
            return None
        path = parsed.path or "/"
        return urllib.parse.urlunsplit(("https", self.host, path, parsed.query, ""))


class _PageParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self._form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() in {"a", "link"} and data.get("href"):
            self.links.append(data["href"])
        elif tag.lower() in {"script", "img", "iframe"} and data.get("src"):
            self.links.append(data["src"])
        elif tag.lower() == "form":
            self._form = {
                "method": (data.get("method") or "GET").upper(),
                "action": data.get("action") or "",
                "inputs": [],
            }
            self.forms.append(self._form)
        elif tag.lower() == "input" and self._form is not None:
            self._form["inputs"].append(
                {"name": data.get("name", ""), "type": (data.get("type") or "text").lower()}
            )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self._form = None


@dataclass
class ProbeStats:
    attempts: int = 0
    new_findings: int = 0
    confirmations: int = 0

    @property
    def yield_rate(self) -> float:
        return self.new_findings / self.attempts if self.attempts else 0.0


class AdaptiveProbeScheduler:
    """Tiny exploration/exploitation scheduler for safe probe families."""

    FAMILIES = ("content_map", "method_surface", "reflection_canary", "error_differential")

    def __init__(self) -> None:
        self.stats = {name: ProbeStats() for name in self.FAMILIES}
        self.total_attempts = 0

    def rank(self) -> list[str]:
        total = max(1, self.total_attempts)

        def score(name: str) -> tuple[float, str]:
            stat = self.stats[name]
            if stat.attempts == 0:
                return (10.0, name)
            exploitation = stat.yield_rate
            exploration = math.sqrt(2.0 * math.log(total + 1) / stat.attempts)
            return (exploitation + exploration, name)

        return [name for name in sorted(self.FAMILIES, key=score, reverse=True)]

    def record(self, family: str, *, new_findings: int, confirmations: int = 0) -> None:
        stat = self.stats[family]
        stat.attempts += 1
        stat.new_findings += max(0, int(new_findings))
        stat.confirmations += max(0, int(confirmations))
        self.total_attempts += 1

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "attempts": stat.attempts,
                "new_findings": stat.new_findings,
                "confirmations": stat.confirmations,
                "yield_rate": round(stat.yield_rate, 4),
            }
            for name, stat in self.stats.items()
        }


@dataclass
class Finding:
    fingerprint: str
    category: str
    url: str
    severity: str
    confidence: float
    evidence: dict[str, Any]
    first_cycle: int
    last_cycle: int
    observations: int = 1
    status: str = "new"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FindingMemory:
    """Deduplicated collective memory for findings shared between cycles/agents."""

    def __init__(self) -> None:
        self._items: dict[str, Finding] = {}

    @staticmethod
    def fingerprint(category: str, url: str, discriminator: str = "") -> str:
        raw = f"{category}\n{url}\n{discriminator}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:20]

    def observe(
        self,
        *,
        category: str,
        url: str,
        severity: str,
        confidence: float,
        evidence: Mapping[str, Any],
        cycle: int,
        discriminator: str = "",
    ) -> tuple[Finding, bool]:
        fp = self.fingerprint(category, url, discriminator)
        existing = self._items.get(fp)
        if existing is not None:
            existing.last_cycle = cycle
            existing.observations += 1
            existing.status = "confirmed"
            existing.confidence = max(existing.confidence, float(confidence))
            existing.evidence.update(dict(evidence))
            return existing, False
        finding = Finding(
            fingerprint=fp,
            category=category,
            url=url,
            severity=severity,
            confidence=max(0.0, min(float(confidence), 1.0)),
            evidence=dict(evidence),
            first_cycle=cycle,
            last_cycle=cycle,
        )
        self._items[fp] = finding
        return finding, True

    def values(self) -> list[Finding]:
        return sorted(self._items.values(), key=lambda item: (item.severity, item.category, item.url))


@dataclass
class LoopLimits:
    max_cycles: int = 3
    max_pages: int = 24
    max_depth: int = 3
    max_requests: int = 80
    families_per_page: int = 3
    stagnant_cycles_to_stop: int = 2


class AuthorizedRangeClosedLoop:
    """Crawl, probe, share, learn, reprioritize, and re-test one authorized host."""

    def __init__(
        self,
        policy: AuthorizedRangePolicy,
        *,
        limits: LoopLimits | None = None,
        client_factory: Callable[[ExternalContactPolicy], ExternalContactClient] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.policy = policy
        self.limits = limits or LoopLimits()
        self.memory = FindingMemory()
        self.scheduler = AdaptiveProbeScheduler()
        self._sleep = sleeper or time.sleep
        transport_policy = ExternalContactPolicy(
            allow_hosts=frozenset({policy.host}),
            allow_http=False,
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            allow_delete=False,
            follow_redirects=policy.follow_redirects,
            max_redirects=policy.max_redirects,
            timeout_seconds=policy.timeout_seconds,
            max_request_bytes=1024,
            max_response_bytes=policy.max_response_bytes,
            retries=policy.retries,
            retry_backoff_seconds=0.25,
        )
        self.client = (client_factory or (lambda p: ExternalContactClient(p)))(transport_policy)
        self.request_count = 0
        self.blocked_out_of_scope = 0
        self._interval = 1.0 / policy.max_rps
        self._page_cache: dict[str, Any] = {}
        self._shared: list[dict[str, Any]] = []

    def _contact(self, url: str, method: str = "GET") -> Any:
        normalized = self.policy.normalize_url(url)
        if normalized is None:
            self.blocked_out_of_scope += 1
            raise AuthorizedRangeLoopError(f"out-of-scope URL blocked: {url}")
        if self.request_count >= self.limits.max_requests:
            raise StopIteration
        result = self.client.contact_with_body(normalized, method=method)
        self.request_count += 1
        if self.request_count < self.limits.max_requests:
            self._sleep(self._interval)
        return result

    def _share(self, finding: Finding, *, family: str, is_new: bool) -> None:
        self._shared.append(
            {
                "schema": "senju-finding-share/v2",
                "fingerprint": finding.fingerprint,
                "category": finding.category,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "url": finding.url,
                "status": finding.status,
                "new": is_new,
                "probe_family": family,
                "next_action": "retest" if is_new else "retain-in-collective-memory",
            }
        )

    def _observe(self, family: str, cycle: int, **kwargs: Any) -> bool:
        finding, is_new = self.memory.observe(cycle=cycle, **kwargs)
        self._share(finding, family=family, is_new=is_new)
        return is_new

    def _parse(self, url: str, body: bytes) -> tuple[list[str], list[dict[str, Any]]]:
        parser = _PageParser()
        try:
            parser.feed(body.decode("utf-8", errors="replace"))
        except Exception:
            return [], []
        links: list[str] = []
        for raw in parser.links:
            normalized = self.policy.normalize_url(raw, base=url)
            if normalized is None:
                if urllib.parse.urlsplit(urllib.parse.urljoin(url, raw)).hostname:
                    self.blocked_out_of_scope += 1
                continue
            links.append(normalized)
        return list(dict.fromkeys(links)), parser.forms

    def _content_map(self, url: str, cycle: int) -> tuple[int, list[str]]:
        result = self._contact(url, "GET")
        self._page_cache[url] = result
        receipt = result.receipt
        links, forms = self._parse(url, result.body)
        new = 0
        if receipt.status >= 500:
            new += self._observe(
                "content_map", cycle,
                category="server_error_surface",
                url=url,
                severity="medium",
                confidence=0.8,
                evidence={"status": receipt.status, "response_sha256": receipt.response_sha256},
                discriminator=str(receipt.status),
            )
        for form in forms:
            method = form.get("method", "GET")
            action = self.policy.normalize_url(str(form.get("action", "")), base=url)
            if action is None:
                new += self._observe(
                    "content_map", cycle,
                    category="cross_origin_form_action",
                    url=url,
                    severity="medium",
                    confidence=0.9,
                    evidence={"method": method, "action": form.get("action", "")},
                    discriminator=str(form.get("action", "")),
                )
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                names = {str(item.get("name", "")).lower() for item in form.get("inputs", [])}
                has_csrf_hint = any("csrf" in name or "token" in name for name in names)
                if not has_csrf_hint:
                    new += self._observe(
                        "content_map", cycle,
                        category="state_form_without_visible_csrf_hint",
                        url=url,
                        severity="low",
                        confidence=0.45,
                        evidence={"method": method, "action": action or form.get("action", "")},
                        discriminator=f"{method}:{action or form.get('action', '')}",
                    )
        return new, links

    def _method_surface(self, url: str, cycle: int) -> int:
        result = self._contact(url, "OPTIONS")
        receipt = result.receipt
        new = 0
        if 500 <= receipt.status:
            new += self._observe(
                "method_surface", cycle,
                category="options_server_error",
                url=url,
                severity="low",
                confidence=0.7,
                evidence={"status": receipt.status},
                discriminator=str(receipt.status),
            )
        return new

    def _reflection_canary(self, url: str, cycle: int) -> int:
        token = f"senju-canary-{hashlib.sha256(url.encode()).hexdigest()[:10]}"
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("senju_probe", token))
        probed = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))
        result = self._contact(probed, "GET")
        if token.encode() in result.body:
            return int(
                self._observe(
                    "reflection_canary", cycle,
                    category="input_reflection",
                    url=url,
                    severity="info",
                    confidence=0.85,
                    evidence={"parameter": "senju_probe", "canary_reflected": True},
                    discriminator="senju_probe",
                )
            )
        return 0

    def _error_differential(self, url: str, cycle: int) -> int:
        baseline = self._page_cache.get(url)
        if baseline is None:
            baseline = self._contact(url, "GET")
            self._page_cache[url] = baseline
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("senju_unknown", "__senju_benign_unknown__"))
        probed = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))
        changed = self._contact(probed, "GET")
        b = baseline.receipt
        c = changed.receipt
        status_changed = b.status != c.status
        body_changed = b.response_sha256 != c.response_sha256
        if status_changed and c.status >= 500:
            return int(
                self._observe(
                    "error_differential", cycle,
                    category="benign_parameter_triggers_server_error",
                    url=url,
                    severity="medium",
                    confidence=0.9,
                    evidence={"baseline_status": b.status, "probe_status": c.status, "body_changed": body_changed},
                    discriminator=f"{b.status}->{c.status}",
                )
            )
        return 0

    def run(self) -> dict[str, Any]:
        queue: deque[tuple[str, int]] = deque([(f"{self.policy.origin}/", 0)])
        seen: set[str] = set()
        cycle_reports: list[dict[str, Any]] = []
        stagnant = 0

        for cycle in range(1, self.limits.max_cycles + 1):
            cycle_new = 0
            cycle_pages = 0
            deferred: deque[tuple[str, int]] = deque()
            ranking = self.scheduler.rank()
            try:
                while queue and len(seen) < self.limits.max_pages:
                    url, depth = queue.popleft()
                    if url in seen or depth > self.limits.max_depth:
                        continue
                    if self.policy.normalize_url(url) is None:
                        self.blocked_out_of_scope += 1
                        continue
                    seen.add(url)
                    cycle_pages += 1
                    families = ranking[: max(1, min(self.limits.families_per_page, len(ranking)))]
                    discovered: list[str] = []
                    for family in families:
                        before = len(self.memory.values())
                        if family == "content_map":
                            found, discovered = self._content_map(url, cycle)
                        elif family == "method_surface":
                            found = self._method_surface(url, cycle)
                        elif family == "reflection_canary":
                            found = self._reflection_canary(url, cycle)
                        else:
                            found = self._error_differential(url, cycle)
                        after = len(self.memory.values())
                        actual_new = max(found, after - before)
                        cycle_new += actual_new
                        self.scheduler.record(family, new_findings=actual_new, confirmations=max(0, 1 if found == 0 else 0))
                    if self.policy.recursive_same_origin and depth < self.limits.max_depth:
                        for link in discovered:
                            if link not in seen:
                                deferred.append((link, depth + 1))
                queue.extend(deferred)
            except StopIteration:
                pass

            cycle_reports.append(
                {
                    "cycle": cycle,
                    "pages_processed": cycle_pages,
                    "new_findings": cycle_new,
                    "request_count_total": self.request_count,
                    "probe_ranking_next": self.scheduler.rank(),
                }
            )
            stagnant = stagnant + 1 if cycle_new == 0 else 0
            if self.request_count >= self.limits.max_requests or stagnant >= self.limits.stagnant_cycles_to_stop:
                break
            if not queue:
                # Re-test known pages so previous findings can be confirmed/regressed.
                queue.extend((url, 0) for url in sorted(seen))
                seen.clear()

        return {
            "schema": "senju-authorized-range-closed-loop/v2",
            "scope_id": self.policy.scope_id,
            "exact_host": self.policy.host,
            "same_origin_only": True,
            "destructive": False,
            "request_count": self.request_count,
            "request_budget": self.limits.max_requests,
            "pages_observed": len(self._page_cache),
            "blocked_out_of_scope": self.blocked_out_of_scope,
            "cycles": cycle_reports,
            "scheduler": self.scheduler.snapshot(),
            "findings": [item.to_dict() for item in self.memory.values()],
            "finding_shares": self._shared,
        }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju's bounded authorized-range closed loop")
    parser.add_argument("--config", default="config/authorized-test-range.json")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--pages", type=int, default=24)
    parser.add_argument("--requests", type=int, default=80)
    parser.add_argument("--out")
    args = parser.parse_args(list(argv) if argv is not None else None)

    policy = AuthorizedRangePolicy.load(args.config)
    limits = LoopLimits(
        max_cycles=max(1, min(args.cycles, 10)),
        max_pages=max(1, min(args.pages, 100)),
        max_requests=max(4, min(args.requests, 500)),
    )
    report = AuthorizedRangeClosedLoop(policy, limits=limits).run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
