"""Deterministic offline adversary campaign for Senju guard surfaces.

All probes are local and non-destructive. Network transports are replaced with fakes,
artifact probes run in temporary directories, and policy/workflow documents are only
mutated in memory. The goal is to make guard failures reproducible and CI-blocking.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .authorized_assessment import EngagementManifest, build_plan
from .autonomy import AutonomyEngine, AutonomyQueue, WorkItem
from .external import ExternalContactClient, ExternalContactPolicy
from .safety import ScopeGuard, ScopeViolation, default_lab_policy
from .scopeguard_adversary import DEFAULT_CASES as SCOPEGUARD_CASES

REPO_ROOT = Path(__file__).resolve().parents[2]
SENJU_ROOT = Path(__file__).resolve().parents[1]
OFFENSE_FIRST_PATH = SENJU_ROOT / "OFFENSE_FIRST.md"
SECURITY_GUARD_PATH = REPO_ROOT / ".github" / "workflows" / "security-guard.yml"
ARTIFACT_GUARD_PATH = REPO_ROOT / "scripts" / "security" / "artifact_guard.py"
FIXED_NOW = dt.datetime(2026, 8, 31, 0, 0, tzinfo=dt.timezone.utc)

TARGETS = (
    "scopeguard",
    "offense-first",
    "engagement-json",
    "external-contact",
    "security-guard",
    "artifact-guard",
    "autonomy-engine",
)

SEVERITY_WEIGHT = {"low": 1, "medium": 3, "high": 7, "critical": 12}


@dataclass(frozen=True)
class ProbeObservation:
    allowed: bool
    detail: str
    side_effect_calls: int = 0
    guard_exception_type: str | None = None


@dataclass(frozen=True)
class GuardCase:
    target: str
    name: str
    family: str
    severity: str
    should_allow: bool
    rationale: str
    probe: Callable[[], ProbeObservation]

    def fingerprint_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "name": self.name,
            "family": self.family,
            "severity": self.severity,
            "should_allow": self.should_allow,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class GuardResult:
    case: GuardCase
    allowed: bool | None
    detail: str
    side_effect_calls: int = 0
    guard_exception_type: str | None = None
    harness_exception_type: str | None = None

    @property
    def surprising(self) -> bool:
        if self.allowed is None or self.allowed != self.case.should_allow:
            return True
        return not self.case.should_allow and self.side_effect_calls > 0

    def to_dict(self) -> dict[str, object]:
        payload = self.case.fingerprint_dict()
        payload.update(
            {
                "allowed": self.allowed,
                "detail": self.detail,
                "side_effect_calls": self.side_effect_calls,
                "guard_exception_type": self.guard_exception_type,
                "harness_exception_type": self.harness_exception_type,
                "surprising": self.surprising,
            }
        )
        return payload


@dataclass(frozen=True)
class MultiGuardReport:
    results: tuple[GuardResult, ...]
    campaign_fingerprint: str

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def surprising(self) -> tuple[GuardResult, ...]:
        return tuple(result for result in self.results if result.surprising)

    @property
    def surprising_count(self) -> int:
        return len(self.surprising)

    @property
    def harness_exception_count(self) -> int:
        return sum(result.allowed is None for result in self.results)

    @property
    def side_effect_violation_count(self) -> int:
        return sum(
            result.side_effect_calls > 0 and not result.case.should_allow
            for result in self.results
        )

    @property
    def passed(self) -> bool:
        return self.surprising_count == 0

    @property
    def risk_score(self) -> int:
        return sum(SEVERITY_WEIGHT.get(result.case.severity, 1) for result in self.surprising)

    def by_target(self) -> dict[str, dict[str, int]]:
        totals = Counter(result.case.target for result in self.results)
        surprises = Counter(result.case.target for result in self.surprising)
        crashes = Counter(result.case.target for result in self.results if result.allowed is None)
        side_effects = Counter(
            result.case.target
            for result in self.results
            if result.side_effect_calls > 0 and not result.case.should_allow
        )
        return {
            target: {
                "total": totals[target],
                "expected": totals[target] - surprises[target],
                "surprising": surprises[target],
                "harness_exceptions": crashes[target],
                "side_effect_violations": side_effects[target],
            }
            for target in sorted(totals)
        }

    def by_family(self) -> dict[str, dict[str, int]]:
        key = lambda result: f"{result.case.target}:{result.case.family}"
        totals = Counter(key(result) for result in self.results)
        surprises = Counter(key(result) for result in self.surprising)
        return {
            family: {
                "total": totals[family],
                "expected": totals[family] - surprises[family],
                "surprising": surprises[family],
            }
            for family in sorted(totals)
        }

    def by_severity(self) -> dict[str, dict[str, int]]:
        totals = Counter(result.case.severity for result in self.results)
        surprises = Counter(result.case.severity for result in self.surprising)
        return {
            severity: {
                "total": totals[severity],
                "surprising": surprises[severity],
            }
            for severity in sorted(totals)
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "senju-multiguard-adversary/v2",
            "campaign_fingerprint": self.campaign_fingerprint,
            "targets": list(TARGETS),
            "total": self.total,
            "surprising_count": self.surprising_count,
            "harness_exception_count": self.harness_exception_count,
            "side_effect_violation_count": self.side_effect_violation_count,
            "risk_score": self.risk_score,
            "passed": self.passed,
            "by_target": self.by_target(),
            "by_family": self.by_family(),
            "by_severity": self.by_severity(),
            "results": [result.to_dict() for result in self.results],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


class _FakeResponse:
    def __init__(self, *, status: int = 204, body: bytes = b"", headers: Mapping[str, str] | None = None) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def close(self) -> None:
        return None


class _CountingOpener:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request, *, timeout: float):  # noqa: ANN001
        self.calls += 1
        return _FakeResponse()


def _fingerprint(cases: Iterable[GuardCase]) -> str:
    digest = hashlib.sha256()
    for case in cases:
        encoded = json.dumps(
            case.fingerprint_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


def _run_case(case: GuardCase) -> GuardResult:
    try:
        observation = case.probe()
    except Exception as exc:
        return GuardResult(
            case=case,
            allowed=None,
            detail=str(exc),
            harness_exception_type=type(exc).__name__,
        )
    return GuardResult(
        case=case,
        allowed=observation.allowed,
        detail=observation.detail,
        side_effect_calls=observation.side_effect_calls,
        guard_exception_type=observation.guard_exception_type,
    )


def run_campaign(cases: Iterable[GuardCase] | None = None) -> MultiGuardReport:
    frozen = tuple(build_campaign() if cases is None else cases)
    return MultiGuardReport(
        results=tuple(_run_case(case) for case in frozen),
        campaign_fingerprint=_fingerprint(frozen),
    )


def validate_offense_first_document(text: str) -> tuple[str, ...]:
    required = {
        "authorized-lab-boundary": "Arena / synthetic / owned-or-explicitly-authorized lab",
        "third-party-authority": "所有者または明示的なテスト権限",
        "external-authorization-boundary": "外部資産に対する認可境界",
        "scope-expansion-authorization": "Owner / BOSS が追加 scope を明示的に認可",
        "bounded-autonomy": "BOSS が与えた上限まで",
    }
    forbidden = {
        "unrestricted-external": "UNAUTHORIZED_EXTERNAL_EXECUTION=ALLOW",
        "implicit-third-party": "THIRD_PARTY_AUTHORIZATION=IMPLICIT",
        "disable-scopeguard": "SCOPEGUARD=DISABLED",
        "allow-any-host": "ALLOW_ANY_HOST=true",
        "unbounded-secrets": "SECRETS_SCOPE=UNRESTRICTED",
        "skip-engagement": "ENGAGEMENT_REQUIRED=false",
        "unbounded-autonomy": "AUTONOMY_BOUNDARY=NONE",
    }
    errors = [f"missing:{name}" for name, marker in required.items() if marker not in text]
    errors.extend(f"forbidden:{name}" for name, marker in forbidden.items() if marker in text)
    return tuple(errors)


def validate_security_guard_workflow(text: str) -> tuple[str, ...]:
    required = {
        "read-only-contents": "contents: read",
        "discard-checkout-credentials": "persist-credentials: false",
        "tracked-secret-files": "Block tracked secret files",
        "tracked-secret-material": "Block obvious credential material in tracked source",
        "new-line-secret-scan": "Scan newly introduced lines for secrets",
        "fail-closed-workflow-policy": "python automation/security/workflow_policy_entrypoint.py",
        "external-evidence-gate": "python automation/security/reality_gate.py",
        "remote-shell-block": "Block remote shell execution patterns",
        "untrusted-interpolation-block": "Block direct interpolation of untrusted event text",
    }
    forbidden = {
        "write-all": "permissions: write-all",
        "checkout-credentials": "persist-credentials: true",
        "pull-request-target": "pull_request_target:",
        "contents-write": "contents: write",
        "actions-write": "actions: write",
        "id-token-write": "id-token: write",
        "packages-write": "packages: write",
        "issues-write": "issues: write",
        "pull-requests-write": "pull-requests: write",
        "checks-write": "checks: write",
        "deployments-write": "deployments: write",
        "statuses-write": "statuses: write",
        "security-events-write": "security-events: write",
        "attestations-write": "attestations: write",
    }
    errors = [f"missing:{name}" for name, marker in required.items() if marker not in text]
    errors.extend(f"forbidden:{name}" for name, marker in forbidden.items() if marker in text)
    return tuple(errors)


def _scopeguard_cases() -> list[GuardCase]:
    guard = ScopeGuard(default_lab_policy())
    cases: list[GuardCase] = []
    for original in SCOPEGUARD_CASES:
        def probe(ref: str = original.target_ref) -> ProbeObservation:
            try:
                guard.check(ref)
            except ScopeViolation as exc:
                return ProbeObservation(False, str(exc), guard_exception_type=type(exc).__name__)
            return ProbeObservation(True, "accepted")

        cases.append(
            GuardCase(
                "scopeguard",
                original.name,
                original.family,
                original.severity,
                original.should_allow,
                original.rationale,
                probe,
            )
        )
    return cases


def _offense_first_cases() -> list[GuardCase]:
    text = OFFENSE_FIRST_PATH.read_text(encoding="utf-8")
    variants = [
        ("baseline", text, True),
        ("blank-document", "", False),
        ("drop-authorized-lab", text.replace("Arena / synthetic / owned-or-explicitly-authorized lab", "Arena / synthetic / lab"), False),
        ("drop-third-party-authority", text.replace("所有者または明示的なテスト権限", "権限"), False),
        ("drop-external-boundary", text.replace("外部資産に対する認可境界", "外部資産の境界"), False),
        ("drop-scope-expansion-approval", text.replace("Owner / BOSS が追加 scope を明示的に認可", "追加 scope"), False),
        ("drop-bounded-autonomy", text.replace("BOSS が与えた上限まで", "上限なし"), False),
        ("confusable-authorized-lab", text.replace("owned-or-explicitly-authorized", "owned-or-explicitly-authorizｅd"), False),
        ("confusable-third-party", text.replace("明示的なテスト権限", "明示的なテスト権 限"), False),
        ("confusable-external-boundary", text.replace("認可境界", "認可 境界"), False),
        ("confusable-scope-approval", text.replace("追加 scope を明示的に認可", "追加 scope を明示的に 認可"), False),
        ("confusable-bounded-autonomy", text.replace("与えた上限まで", "与えた上 限まで"), False),
        ("inject-unrestricted-external", text + "\nUNAUTHORIZED_EXTERNAL_EXECUTION=ALLOW\n", False),
        ("inject-implicit-third-party", text + "\nTHIRD_PARTY_AUTHORIZATION=IMPLICIT\n", False),
        ("inject-disable-scopeguard", text + "\nSCOPEGUARD=DISABLED\n", False),
        ("inject-allow-any-host", text + "\nALLOW_ANY_HOST=true\n", False),
        ("inject-unbounded-secrets", text + "\nSECRETS_SCOPE=UNRESTRICTED\n", False),
        ("inject-skip-engagement", text + "\nENGAGEMENT_REQUIRED=false\n", False),
        ("inject-unbounded-autonomy", text + "\nAUTONOMY_BOUNDARY=NONE\n", False),
        ("drop-two-boundaries", text.replace("所有者または明示的なテスト権限", "権限").replace("外部資産に対する認可境界", "外部境界"), False),
    ]
    assert len(variants) == 20
    return [
        GuardCase(
            "offense-first",
            name,
            "document-contract",
            "high" if not expected else "low",
            expected,
            "authorization doctrine must retain explicit bounded external authority",
            lambda value=candidate: ProbeObservation(
                not (errors := validate_offense_first_document(value)),
                "; ".join(errors) if errors else "contract intact",
            ),
        )
        for name, candidate, expected in variants
    ]


def _base_engagement() -> dict[str, object]:
    return {
        "engagement_id": "adv-20260831",
        "owner": "adversary-fixture-owner",
        "authorization_reference": "fixture://explicit-authority",
        "valid_from_utc": "2026-08-30T00:00:00Z",
        "valid_until_utc": "2026-09-02T00:00:00Z",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "security_txt"],
        "max_requests_per_target": 2,
        "max_rps": 1.0,
        "allow_http": False,
        "destructive": False,
    }


def _engagement_probe(raw: Mapping[str, object]) -> ProbeObservation:
    try:
        manifest = EngagementManifest.from_dict(raw)
        manifest.validate(now=FIXED_NOW, enforce_window=True)
        plan = build_plan(manifest)
        approved_hosts = {target.host for target in manifest.targets}
        for request in plan:
            parsed = urllib.parse.urlsplit(request.url)
            if request.target_host not in approved_hosts or parsed.hostname not in approved_hosts:
                raise AssertionError("plan escaped exact engagement host set")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                raise AssertionError("plan emitted a non-passive method")
    except Exception as exc:
        return ProbeObservation(False, str(exc), guard_exception_type=type(exc).__name__)
    return ProbeObservation(True, f"manifest accepted; bounded plan size={len(plan)}")


def _engagement_cases() -> list[GuardCase]:
    base = _base_engagement()
    specs: list[tuple[str, Callable[[dict[str, object]], None], bool, str]] = [
        ("valid-window", lambda raw: None, True, "baseline"),
        ("standing-window-omitted", lambda raw: (raw.__setitem__("valid_from_utc", ""), raw.__setitem__("valid_until_utc", "")), True, "window"),
        ("valid-base-path", lambda raw: raw.__setitem__("targets", [{"host": "example.com", "scheme": "https", "base_path": "/safe"}]), True, "target"),
        ("http-explicit-optin", lambda raw: (raw.__setitem__("allow_http", True), raw.__setitem__("targets", [{"host": "example.com", "scheme": "http"}])), True, "scheme"),
        ("request-budget-min", lambda raw: raw.__setitem__("max_requests_per_target", 1), True, "budget"),
        ("request-budget-max", lambda raw: raw.__setitem__("max_requests_per_target", 8), True, "budget"),
        ("rps-min", lambda raw: raw.__setitem__("max_rps", 0.1), True, "budget"),
        ("rps-max", lambda raw: raw.__setitem__("max_rps", 2.0), True, "budget"),
        ("owner-missing", lambda raw: raw.__setitem__("owner", ""), False, "required-field"),
        ("authorization-missing", lambda raw: raw.__setitem__("authorization_reference", ""), False, "required-field"),
        ("targets-empty", lambda raw: raw.__setitem__("targets", []), False, "target"),
        ("targets-wrong-type", lambda raw: raw.__setitem__("targets", {"host": "example.com"}), False, "type-confusion"),
        ("target-scalar", lambda raw: raw.__setitem__("targets", [7]), False, "type-confusion"),
        ("host-empty", lambda raw: raw.__setitem__("targets", [{"host": ""}]), False, "target"),
        ("wildcard-host", lambda raw: raw.__setitem__("targets", [{"host": "*.example.com"}]), False, "target"),
        ("url-shaped-host", lambda raw: raw.__setitem__("targets", [{"host": "https://example.com"}]), False, "target"),
        ("userinfo-host", lambda raw: raw.__setitem__("targets", [{"host": "user@example.com"}]), False, "target"),
        ("fragment-host", lambda raw: raw.__setitem__("targets", [{"host": "example.com#x"}]), False, "target"),
        ("unknown-check", lambda raw: raw.__setitem__("allowed_checks", ["reachability", "exploit"]), False, "capability"),
        ("checks-empty", lambda raw: raw.__setitem__("allowed_checks", []), False, "capability"),
        ("destructive", lambda raw: raw.__setitem__("destructive", True), False, "capability"),
        ("request-budget-zero", lambda raw: raw.__setitem__("max_requests_per_target", 0), False, "budget"),
        ("request-budget-nine", lambda raw: raw.__setitem__("max_requests_per_target", 9), False, "budget"),
        ("request-budget-string", lambda raw: raw.__setitem__("max_requests_per_target", "2"), False, "type-confusion"),
        ("request-budget-bool", lambda raw: raw.__setitem__("max_requests_per_target", True), False, "type-confusion"),
        ("rps-under-limit", lambda raw: raw.__setitem__("max_rps", 0.09), False, "budget"),
        ("rps-over-limit", lambda raw: raw.__setitem__("max_rps", 2.01), False, "budget"),
        ("rps-string", lambda raw: raw.__setitem__("max_rps", "1.0"), False, "type-confusion"),
        ("rps-bool", lambda raw: raw.__setitem__("max_rps", True), False, "type-confusion"),
        ("http-no-optin", lambda raw: raw.__setitem__("targets", [{"host": "example.com", "scheme": "http"}]), False, "scheme"),
        ("duplicate-target", lambda raw: raw.__setitem__("targets", [{"host": "example.com"}, {"host": "example.com"}]), False, "target"),
        ("one-sided-window-start", lambda raw: raw.__setitem__("valid_until_utc", ""), False, "window"),
        ("one-sided-window-end", lambda raw: raw.__setitem__("valid_from_utc", ""), False, "window"),
        ("reversed-window", lambda raw: (raw.__setitem__("valid_from_utc", "2026-09-02T00:00:00Z"), raw.__setitem__("valid_until_utc", "2026-08-30T00:00:00Z")), False, "window"),
        ("expired-window", lambda raw: (raw.__setitem__("valid_from_utc", "2026-08-01T00:00:00Z"), raw.__setitem__("valid_until_utc", "2026-08-02T00:00:00Z")), False, "window"),
        ("future-window", lambda raw: (raw.__setitem__("valid_from_utc", "2026-09-10T00:00:00Z"), raw.__setitem__("valid_until_utc", "2026-09-11T00:00:00Z")), False, "window"),
        ("allow-http-string-false", lambda raw: (raw.__setitem__("allow_http", "false"), raw.__setitem__("targets", [{"host": "example.com", "scheme": "http"}])), False, "type-confusion"),
        ("allow-http-int-one", lambda raw: raw.__setitem__("allow_http", 1), False, "type-confusion"),
        ("destructive-string-false", lambda raw: raw.__setitem__("destructive", "false"), False, "type-confusion"),
        ("destructive-int-zero", lambda raw: raw.__setitem__("destructive", 0), False, "type-confusion"),
    ]
    assert len(specs) == 40
    cases: list[GuardCase] = []
    for name, mutate, expected, family in specs:
        raw = copy.deepcopy(base)
        mutate(raw)
        cases.append(
            GuardCase(
                "engagement-json",
                name,
                family,
                "high" if not expected else "low",
                expected,
                "machine-readable authority and plan construction must fail closed",
                lambda value=raw: _engagement_probe(value),
            )
        )
    return cases


def _external_probe(
    *,
    url: str = "https://example.com/",
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    allow_hosts: Iterable[str] = ("example.com",),
    allow_http: bool = False,
    allow_delete: bool = False,
    resolver_ips: tuple[str, ...] = ("93.184.216.34",),
) -> ProbeObservation:
    opener = _CountingOpener()
    try:
        policy = ExternalContactPolicy.from_hosts(
            allow_hosts,
            allow_http=allow_http,
            allow_delete=allow_delete,
            retries=0,
        )
        client = ExternalContactClient(
            policy,
            resolver=lambda host, port: resolver_ips,
            opener=opener,
            sleeper=lambda seconds: None,
        )
        client.contact_with_body(url, method=method, body=body, headers=headers)
    except Exception as exc:
        return ProbeObservation(False, str(exc), opener.calls, type(exc).__name__)
    return ProbeObservation(True, "fake transport accepted request", opener.calls)


def _external_cases() -> list[GuardCase]:
    specs: list[tuple[str, dict[str, object], bool, str]] = [
        ("https-get", {}, True, "baseline"),
        ("https-head", {"method": "HEAD"}, True, "method"),
        ("https-options", {"method": "OPTIONS"}, True, "method"),
        ("https-post-small-body", {"method": "POST", "body": b"{}"}, True, "method"),
        ("https-put-small-body", {"method": "PUT", "body": b"{}"}, True, "method"),
        ("https-patch-small-body", {"method": "PATCH", "body": b"{}"}, True, "method"),
        ("https-delete-explicit", {"method": "DELETE", "body": b"{}", "allow_delete": True}, True, "method"),
        ("unlisted-host", {"url": "https://other.example/"}, False, "allowlist"),
        ("subdomain-not-allowlisted", {"url": "https://sub.example.com/"}, False, "allowlist"),
        ("suffix-confusion", {"url": "https://example.com.evil.invalid/"}, False, "allowlist"),
        ("plain-http-disabled", {"url": "http://example.com/"}, False, "scheme"),
        ("unsupported-scheme", {"url": "ftp://example.com/"}, False, "scheme"),
        ("userinfo", {"url": "https://user@example.com/"}, False, "authority"),
        ("userinfo-password", {"url": "https://user:pass@example.com/"}, False, "authority"),
        ("invalid-port", {"url": "https://example.com:notaport/"}, False, "authority"),
        ("port-out-of-range", {"url": "https://example.com:70000/"}, False, "authority"),
        ("trace-method", {"method": "TRACE"}, False, "method"),
        ("connect-method", {"method": "CONNECT"}, False, "method"),
        ("delete-no-optin", {"method": "DELETE"}, False, "method"),
        ("get-with-body", {"method": "GET", "body": b"x"}, False, "body"),
        ("head-with-body", {"method": "HEAD", "body": b"x"}, False, "body"),
        ("options-with-body", {"method": "OPTIONS", "body": b"x"}, False, "body"),
        ("oversized-body", {"method": "POST", "body": b"x" * (64 * 1024 + 1)}, False, "body"),
        ("caller-host-header", {"headers": {"Host": "other.example"}}, False, "headers"),
        ("caller-content-length", {"headers": {"Content-Length": "1"}}, False, "headers"),
        ("caller-transfer-encoding", {"headers": {"Transfer-Encoding": "chunked"}}, False, "headers"),
        ("header-name-colon", {"headers": {"X:Bad": "1"}}, False, "headers"),
        ("header-name-crlf", {"headers": {"X-Test\nInjected": "1"}}, False, "headers"),
        ("header-value-crlf", {"headers": {"X-Test": "ok\r\nInjected: 1"}}, False, "headers"),
        ("private-resolver-v4", {"resolver_ips": ("127.0.0.1",)}, False, "dns"),
        ("private-resolver-v6", {"resolver_ips": ("::1",)}, False, "dns"),
        ("empty-resolver-result", {"resolver_ips": ()}, False, "dns"),
        ("invalid-resolver-result", {"resolver_ips": ("not-an-ip",)}, False, "dns"),
        ("url-shaped-allowlist", {"allow_hosts": ("https://example.com",)}, False, "lexical"),
        ("nul-allowlist-and-url", {"allow_hosts": ("example.com\x00",), "url": "https://example.com\x00/"}, False, "lexical"),
    ]
    assert len(specs) == 35
    return [
        GuardCase(
            "external-contact",
            name,
            family,
            "high" if not expected else "low",
            expected,
            "blocked outbound requests must stop before the fake transport boundary",
            lambda kwargs=kwargs: _external_probe(**kwargs),
        )
        for name, kwargs, expected, family in specs
    ]


def _security_guard_cases() -> list[GuardCase]:
    text = SECURITY_GUARD_PATH.read_text(encoding="utf-8")
    required_markers = [
        "contents: read",
        "persist-credentials: false",
        "Block tracked secret files",
        "Block obvious credential material in tracked source",
        "Scan newly introduced lines for secrets",
        "python automation/security/workflow_policy_entrypoint.py",
        "python automation/security/reality_gate.py",
        "Block remote shell execution patterns",
        "Block direct interpolation of untrusted event text",
    ]
    forbidden_markers = [
        "permissions: write-all",
        "persist-credentials: true",
        "pull_request_target:",
        "contents: write",
        "actions: write",
        "id-token: write",
        "packages: write",
        "issues: write",
        "pull-requests: write",
        "checks: write",
        "deployments: write",
        "statuses: write",
        "security-events: write",
        "attestations: write",
    ]
    mutations: list[tuple[str, str, bool]] = [("baseline", text, True), ("blank", "", False)]
    for idx, marker in enumerate(required_markers, 1):
        mutations.append((f"drop-required-{idx:02d}", text.replace(marker, f"REMOVED_REQUIRED_{idx}", 1), False))
    for idx, marker in enumerate(forbidden_markers, 1):
        mutations.append((f"inject-forbidden-{idx:02d}", text + f"\n{marker}\n", False))
    assert len(mutations) == 25
    return [
        GuardCase(
            "security-guard",
            name,
            "workflow-contract",
            "critical" if not expected else "low",
            expected,
            "security workflow must fail closed when gates or least privilege regress",
            lambda value=candidate: ProbeObservation(
                not (errors := validate_security_guard_workflow(value)),
                "; ".join(errors) if errors else "workflow contract intact",
            ),
        )
        for name, candidate, expected in mutations
    ]


def _artifact_probe(filename: str, content: bytes) -> ProbeObservation:
    with tempfile.TemporaryDirectory(prefix="senju-artifact-adversary-") as tmp:
        root = Path(tmp)
        dist = root / "dist"
        dist.mkdir()
        artifact = dist / filename
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(content)
        report_path = root / "report.json"
        proc = subprocess.run(
            [sys.executable, str(ARTIFACT_GUARD_PATH), str(dist), "--json", str(report_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        findings = payload.get("findings", [])
        rules = [str(item.get("rule", "")) for item in findings if isinstance(item, dict)]
        return ProbeObservation(proc.returncode == 0, ",".join(rules) if rules else "artifact accepted")


def _artifact_cases() -> list[GuardCase]:
    ghp = ("ghp_" + "A" * 24).encode()
    gho = ("gho_" + "B" * 24).encode()
    ghpat = ("github_pat_" + "C" * 24).encode()
    openai = ("sk-" + "D" * 24).encode()
    private_key = b"-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----"
    rsa_key = b"-----BEGIN RSA PRIVATE KEY-----\nfixture\n-----END RSA PRIVATE KEY-----"
    slack_b = ("xoxb-" + "E" * 24).encode()
    slack_a = ("xoxa-" + "F" * 24).encode()
    specs: list[tuple[str, str, bytes, bool, str]] = [
        ("safe-html", "index.html", b"<a href='https://example.com/'>ok</a>", True, "baseline"),
        ("safe-js", "app.js", b"fetch('https://example.com/data')", True, "baseline"),
        ("safe-json", "data.json", b'{"ok":true}', True, "baseline"),
        ("safe-css", "app.css", b"body{background:url(https://example.com/a.png)}", True, "baseline"),
        ("safe-svg", "icon.svg", b"<svg><image href='https://example.com/a.png'/></svg>", True, "baseline"),
        ("safe-txt", "readme.txt", b"public fixture", True, "baseline"),
        ("source-map-file", "app.js.map", b"{}", False, "source-map"),
        ("source-map-reference-js", "app.js", b"//# sourceMappingURL=app.js.map", False, "source-map"),
        ("source-map-reference-css", "app.css", b"/*# sourceMappingURL=app.css.map */", False, "source-map"),
        ("localhost-html", "index.html", b"<img src='http://localhost:3000/x.png'>", False, "localhost"),
        ("localhost-js", "app.js", b"fetch('http://localhost:8000/api')", False, "localhost"),
        ("localhost-css", "app.css", b"body{background:url(http://localhost/a.png)}", False, "localhost"),
        ("loopback-html", "index.html", b"<img src='http://127.0.0.1:3000/x.png'>", False, "localhost"),
        ("mixed-html-src", "index.html", b"<script src='http://example.com/app.js'></script>", False, "mixed-content"),
        ("mixed-html-href", "index.html", b"<a href='http://example.com/'>x</a>", False, "mixed-content"),
        ("mixed-css", "app.css", b"body{background:url(http://example.com/a.png)}", False, "mixed-content"),
        ("mixed-xml", "sitemap.xml", b"<url><loc>http://example.com/a</loc></url>", False, "mixed-content"),
        ("mixed-js-fetch", "app.js", b"fetch('http://example.com/a')", False, "mixed-content"),
        ("mixed-js-new-url", "app.js", b"new URL('http://example.com/a')", False, "mixed-content"),
        ("mixed-js-src", "app.js", b"img.src='http://example.com/a'", False, "mixed-content"),
        ("mixed-js-href", "app.js", b"link.href='http://example.com/a'", False, "mixed-content"),
        ("github-ghp-token", "app.js", ghp, False, "secret"),
        ("github-gho-token", "app.js", gho, False, "secret"),
        ("github-pat-token", "app.js", ghpat, False, "secret"),
        ("openai-token", "app.js", openai, False, "secret"),
        ("private-key", "app.txt", private_key, False, "secret"),
        ("rsa-private-key", "app.txt", rsa_key, False, "secret"),
        ("slack-bot-token", "app.js", slack_b, False, "secret"),
        ("slack-app-token", "app.js", slack_a, False, "secret"),
        ("nested-source-map", "assets/chunks/app.js.map", b"{}", False, "source-map"),
    ]
    assert len(specs) == 30
    return [
        GuardCase(
            "artifact-guard",
            name,
            family,
            "high" if not expected else "low",
            expected,
            "built artifacts are scanned by the real guard in isolated temporary output",
            lambda n=filename, body=content: _artifact_probe(n, body),
        )
        for name, filename, content, expected, family in specs
    ]


def _work_item_probe(**overrides: object) -> ProbeObservation:
    data: dict[str, object] = {
        "item_id": "adv-item",
        "hypothesis": "bounded local adversary fixture",
        "category": "resilience",
        "expected_value": 0.7,
        "cost_budget_matches": 100,
        "runtime_seconds_budget": 30.0,
        "max_retries": 2,
        "authority_scope": "none",
        "parameters": {"population": 20, "generations": 5, "matches": 100, "mutation_rate": 0.1},
    }
    data.update(overrides)
    try:
        WorkItem(**data)  # type: ignore[arg-type]
    except Exception as exc:
        return ProbeObservation(False, str(exc), guard_exception_type=type(exc).__name__)
    return ProbeObservation(True, "work item accepted")


def _autonomy_queue_roundtrip_probe() -> ProbeObservation:
    with tempfile.TemporaryDirectory(prefix="senju-autonomy-adversary-") as tmp:
        path = Path(tmp) / "queue.json"
        queue = AutonomyQueue(path)
        item = WorkItem(
            item_id="roundtrip",
            hypothesis="roundtrip fixture",
            category="resilience",
            expected_value=0.5,
            cost_budget_matches=50,
            parameters={"population": 10, "generations": 2, "matches": 50, "mutation_rate": 0.1},
        )
        if not queue.enqueue(item):
            return ProbeObservation(False, "initial enqueue rejected")
        loaded = AutonomyQueue(path)
        if "roundtrip" not in loaded._items:
            return ProbeObservation(False, "persisted item disappeared")
        selected = loaded.select_next(budget_matches=50)
        if selected is None or selected.item_id != "roundtrip":
            return ProbeObservation(False, "bounded selector did not recover persisted item")
        return ProbeObservation(True, "queue persisted and selected within budget")


def _autonomy_engine_seed_probe() -> ProbeObservation:
    with tempfile.TemporaryDirectory(prefix="senju-autonomy-engine-adversary-") as tmp:
        engine = AutonomyEngine(tmp)
        items = tuple(engine.queue._items.values())
        if len(items) != 3:
            return ProbeObservation(False, f"expected 3 seed items, got {len(items)}")
        if any(item.cost_budget_matches > 5000 for item in items):
            return ProbeObservation(False, "seed item exceeded bounded match budget")
        return ProbeObservation(True, "engine seeded bounded local hypotheses")


def _autonomy_cases() -> list[GuardCase]:
    specs: list[tuple[str, Callable[[], ProbeObservation], bool, str]] = [
        ("valid-default", lambda: _work_item_probe(), True, "baseline"),
        ("valid-threat-intel", lambda: _work_item_probe(authority_scope="threat_intel_public", category="threat_intel"), True, "authority"),
        ("valid-canary", lambda: _work_item_probe(authority_scope="canary_telemetry"), True, "authority"),
        ("valid-high-boundaries", lambda: _work_item_probe(expected_value=1.0, cost_budget_matches=5000, runtime_seconds_budget=600.0, max_retries=10, parameters={"population": 256, "generations": 100, "matches": 5000, "mutation_rate": 1.0}), True, "budget"),
        ("queue-roundtrip", _autonomy_queue_roundtrip_probe, True, "persistence"),
        ("engine-seeds-bounded", _autonomy_engine_seed_probe, True, "engine"),
        ("blank-id", lambda: _work_item_probe(item_id=""), False, "identity"),
        ("blank-hypothesis", lambda: _work_item_probe(hypothesis=""), False, "identity"),
        ("unknown-category", lambda: _work_item_probe(category="unknown"), False, "capability"),
        ("expected-negative", lambda: _work_item_probe(expected_value=-0.01), False, "budget"),
        ("expected-over-one", lambda: _work_item_probe(expected_value=1.01), False, "budget"),
        ("expected-string", lambda: _work_item_probe(expected_value="0.5"), False, "type-confusion"),
        ("cost-zero", lambda: _work_item_probe(cost_budget_matches=0), False, "budget"),
        ("cost-over-max", lambda: _work_item_probe(cost_budget_matches=5001), False, "budget"),
        ("cost-bool", lambda: _work_item_probe(cost_budget_matches=True), False, "type-confusion"),
        ("runtime-zero", lambda: _work_item_probe(runtime_seconds_budget=0.0), False, "budget"),
        ("runtime-over-max", lambda: _work_item_probe(runtime_seconds_budget=600.1), False, "budget"),
        ("retries-negative", lambda: _work_item_probe(max_retries=-1), False, "budget"),
        ("retries-over-max", lambda: _work_item_probe(max_retries=11), False, "budget"),
        ("authority-unknown", lambda: _work_item_probe(authority_scope="anything"), False, "authority"),
        ("parameters-not-dict", lambda: _work_item_probe(parameters=[]), False, "type-confusion"),
        ("population-zero", lambda: _work_item_probe(parameters={"population": 0}), False, "resource-bound"),
        ("population-over-max", lambda: _work_item_probe(parameters={"population": 257}), False, "resource-bound"),
        ("generations-zero", lambda: _work_item_probe(parameters={"generations": 0}), False, "resource-bound"),
        ("generations-over-max", lambda: _work_item_probe(parameters={"generations": 101}), False, "resource-bound"),
        ("matches-zero", lambda: _work_item_probe(parameters={"matches": 0}), False, "resource-bound"),
        ("matches-over-max", lambda: _work_item_probe(parameters={"matches": 5001}), False, "resource-bound"),
        ("mutation-negative", lambda: _work_item_probe(parameters={"mutation_rate": -0.01}), False, "resource-bound"),
        ("mutation-over-one", lambda: _work_item_probe(parameters={"mutation_rate": 1.01}), False, "resource-bound"),
        ("status-unknown", lambda: _work_item_probe(status="unknown"), False, "state"),
    ]
    assert len(specs) == 30
    return [
        GuardCase(
            "autonomy-engine",
            name,
            family,
            "high" if not expected else "low",
            expected,
            "autonomy queue and engine inputs must remain bounded, typed, and durable",
            probe,
        )
        for name, probe, expected, family in specs
    ]


def build_campaign(*, targets: Iterable[str] | None = None) -> tuple[GuardCase, ...]:
    """Build the deterministic seven-target campaign (300 cases when unfiltered)."""
    selected = set(TARGETS if targets is None else targets)
    unknown = selected - set(TARGETS)
    if unknown:
        raise ValueError(f"unknown adversary target(s): {sorted(unknown)}")
    builders: tuple[tuple[str, Callable[[], list[GuardCase]]], ...] = (
        ("scopeguard", _scopeguard_cases),
        ("offense-first", _offense_first_cases),
        ("engagement-json", _engagement_cases),
        ("external-contact", _external_cases),
        ("security-guard", _security_guard_cases),
        ("artifact-guard", _artifact_cases),
        ("autonomy-engine", _autonomy_cases),
    )
    cases: list[GuardCase] = []
    for target, builder in builders:
        if target in selected:
            cases.extend(builder())
    if targets is None and len(cases) != 300:
        raise AssertionError(f"full campaign drifted from 300 cases: {len(cases)}")
    identities = [(case.target, case.name) for case in cases]
    if len(identities) != len(set(identities)):
        raise AssertionError("duplicate adversary case identity")
    return tuple(cases)
