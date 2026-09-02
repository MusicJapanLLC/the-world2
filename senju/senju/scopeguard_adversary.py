"""Deterministic adversarial test harness for ScopeGuard.

The harness never performs network I/O and never changes ScopeGuard policy. It
stress-tests target_ref parsing/decision behavior with a reproducible campaign,
captures unexpected decisions/exceptions, and emits machine-readable reports.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from .safety import ScopeGuard, ScopeViolation


@dataclass(frozen=True)
class ProbeCase:
    name: str
    target_ref: str
    should_allow: bool
    family: str = "baseline"
    severity: str = "medium"
    rationale: str = ""


@dataclass(frozen=True)
class ProbeResult:
    case: ProbeCase
    allowed: bool | None
    detail: str
    exception_type: str | None = None

    @property
    def surprising(self) -> bool:
        return self.allowed is None or self.allowed != self.case.should_allow


@dataclass(frozen=True)
class AdversaryReport:
    results: tuple[ProbeResult, ...]
    campaign_fingerprint: str

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def surprising(self) -> tuple[ProbeResult, ...]:
        return tuple(result for result in self.results if result.surprising)

    @property
    def surprising_count(self) -> int:
        return len(self.surprising)

    @property
    def exception_count(self) -> int:
        return sum(result.allowed is None for result in self.results)

    @property
    def passed(self) -> bool:
        return self.surprising_count == 0

    def by_family(self) -> dict[str, dict[str, int]]:
        totals = Counter(result.case.family for result in self.results)
        surprises = Counter(result.case.family for result in self.surprising)
        return {
            family: {
                "total": totals[family],
                "surprising": surprises[family],
                "expected": totals[family] - surprises[family],
            }
            for family in sorted(totals)
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_fingerprint": self.campaign_fingerprint,
            "total": self.total,
            "surprising_count": self.surprising_count,
            "exception_count": self.exception_count,
            "passed": self.passed,
            "by_family": self.by_family(),
            "results": [
                {
                    "case": asdict(result.case),
                    "allowed": result.allowed,
                    "detail": result.detail,
                    "exception_type": result.exception_type,
                    "surprising": result.surprising,
                }
                for result in self.results
            ],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )


BASELINE_CASES: tuple[ProbeCase, ...] = (
    ProbeCase("empty", "", False, "empty", "high", "empty refs must fail closed"),
    ProbeCase("plain-public-host", "example.com", False, "public", "high"),
    ProbeCase("public-host-leading-space", " example.com", False, "public", "high"),
    ProbeCase("public-host-trailing-space", "example.com ", False, "public", "high"),
    ProbeCase("public-url-http", "http://example.com", False, "public", "high"),
    ProbeCase("public-url-https", "https://example.com", False, "public", "high"),
    ProbeCase("public-host-uppercase", "EXAMPLE.COM", False, "public", "medium"),
    ProbeCase("loopback-v4", "127.0.0.1", False, "private", "high"),
    ProbeCase("loopback-v4-with-port", "127.0.0.1:8000", False, "private", "high"),
    ProbeCase("loopback-v6", "::1", False, "private", "high"),
    ProbeCase("private-v4", "10.0.0.1", False, "private", "high"),
    ProbeCase("private-v4-with-port", "10.0.0.1:443", False, "private", "high"),
    ProbeCase("link-local", "169.254.1.1", False, "private", "high"),
    ProbeCase("labnet-prefix", "labnet:example", False, "labnet", "medium"),
    ProbeCase("simulated", "sim://fixture", True, "simulated", "low"),
    ProbeCase("sim-lookalike-case", "SIM://fixture", False, "simulated", "medium"),
    ProbeCase("sim-leading-space", " sim://fixture", False, "simulated", "medium"),
    ProbeCase("sim-prefix-only", "sim://", True, "simulated", "low"),
)

PUBLIC_HOST_SEEDS: tuple[str, ...] = (
    "example.com",
    "203.0.113.10",
    "198.51.100.7",
)

PRIVATE_HOST_SEEDS: tuple[str, ...] = (
    "127.0.0.1",
    "10.0.0.1",
    "169.254.1.1",
    "::1",
)

SIMULATED_SEEDS: tuple[str, ...] = (
    "sim://fixture",
    "sim://alpha",
)


def _unique_cases(cases: Iterable[ProbeCase]) -> tuple[ProbeCase, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[ProbeCase] = []
    for case in cases:
        key = (case.name, case.target_ref)
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return tuple(unique)


def _public_mutations(seed: str, index: int) -> tuple[ProbeCase, ...]:
    variants = (
        ("leading-space", f" {seed}"),
        ("trailing-space", f"{seed} "),
        ("tab-prefix", f"\t{seed}"),
        ("newline-suffix", f"{seed}\n"),
        ("http", f"http://{seed}"),
        ("https", f"https://{seed}"),
        ("double-slash", f"//{seed}"),
        ("userinfo", f"user@{seed}"),
        ("fragment", f"{seed}#fragment"),
        ("query", f"{seed}?probe=1"),
        ("path", f"{seed}/path"),
        ("trailing-dot", f"{seed}."),
        ("mixed-case", seed.swapcase()),
        ("nul-suffix", f"{seed}\x00"),
    )
    return tuple(
        ProbeCase(
            name=f"public-{index}-{label}",
            target_ref=value,
            should_allow=False,
            family="public-mutation",
            severity="high",
            rationale="public-like mutations must stay outside strict default scope",
        )
        for label, value in variants
    )


def _private_mutations(seed: str, index: int) -> tuple[ProbeCase, ...]:
    variants = (
        ("leading-space", f" {seed}"),
        ("trailing-space", f"{seed} "),
        ("http", f"http://{seed}"),
        ("https", f"https://{seed}"),
        ("port-80", f"{seed}:80"),
        ("port-443", f"{seed}:443"),
        ("fragment", f"{seed}#x"),
        ("query", f"{seed}?x=1"),
        ("nul-suffix", f"{seed}\x00"),
    )
    return tuple(
        ProbeCase(
            name=f"private-{index}-{label}",
            target_ref=value,
            should_allow=False,
            family="private-mutation",
            severity="high",
            rationale="private-network references must remain rejected in default policy",
        )
        for label, value in variants
    )


def _simulated_mutations(seed: str, index: int) -> tuple[ProbeCase, ...]:
    variants = (
        ("leading-space", f" {seed}"),
        ("trailing-space", f"{seed} "),
        ("leading-tab", f"\t{seed}"),
        ("tab-suffix", f"{seed}\t"),
        ("newline-suffix", f"{seed}\n"),
        ("carriage-return-suffix", f"{seed}\r"),
        ("uppercase-scheme", seed.replace("sim://", "SIM://", 1)),
        ("mixed-scheme", seed.replace("sim://", "Sim://", 1)),
        ("backslash", seed.replace("sim://", r"sim:\\", 1)),
        ("fullwidth-colon", seed.replace(":", "：", 1)),
        ("nul-prefix", f"\x00{seed}"),
        ("nul-suffix", f"{seed}\x00"),
    )
    return tuple(
        ProbeCase(
            name=f"sim-{index}-{label}",
            target_ref=value,
            should_allow=False,
            family="simulated-mutation",
            severity="medium",
            rationale="lookalike/ambiguous lexical variants should not inherit simulated trust",
        )
        for label, value in variants
    )


def build_campaign(
    *,
    include_baseline: bool = True,
    include_generated: bool = True,
) -> tuple[ProbeCase, ...]:
    """Build a deterministic, offline adversarial campaign."""
    cases: list[ProbeCase] = []
    if include_baseline:
        cases.extend(BASELINE_CASES)

    if include_generated:
        for index, seed in enumerate(PUBLIC_HOST_SEEDS):
            cases.extend(_public_mutations(seed, index))
        for index, seed in enumerate(PRIVATE_HOST_SEEDS):
            cases.extend(_private_mutations(seed, index))
        for index, seed in enumerate(SIMULATED_SEEDS):
            cases.extend(_simulated_mutations(seed, index))

    return _unique_cases(cases)


DEFAULT_CASES = build_campaign()


def _fingerprint(cases: Iterable[ProbeCase]) -> str:
    digest = hashlib.sha256()
    for case in cases:
        digest.update(case.family.encode("utf-8"))
        digest.update(b"\0")
        digest.update(case.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(case.target_ref.encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"1" if case.should_allow else b"0")
        digest.update(b"\n")
    return digest.hexdigest()


def probe_guard(
    guard: ScopeGuard,
    cases: Iterable[ProbeCase] = DEFAULT_CASES,
) -> list[ProbeResult]:
    """Run probes against ScopeGuard.check and isolate unexpected exceptions."""
    results: list[ProbeResult] = []
    for case in tuple(cases):
        try:
            guard.check(case.target_ref)
        except ScopeViolation as exc:
            results.append(
                ProbeResult(
                    case=case,
                    allowed=False,
                    detail=str(exc),
                    exception_type=type(exc).__name__,
                )
            )
        except Exception as exc:  # defensive: harness must report, not crash campaign
            results.append(
                ProbeResult(
                    case=case,
                    allowed=None,
                    detail=str(exc),
                    exception_type=type(exc).__name__,
                )
            )
        else:
            results.append(ProbeResult(case=case, allowed=True, detail="accepted"))
    return results


def run_campaign(
    guard: ScopeGuard,
    cases: Iterable[ProbeCase] = DEFAULT_CASES,
) -> AdversaryReport:
    """Run a campaign and return a reproducible structured report."""
    frozen_cases = tuple(cases)
    return AdversaryReport(
        results=tuple(probe_guard(guard, frozen_cases)),
        campaign_fingerprint=_fingerprint(frozen_cases),
    )


def surprising_results(
    guard: ScopeGuard,
    cases: Iterable[ProbeCase] = DEFAULT_CASES,
) -> list[ProbeResult]:
    """Return only behavior that differs from campaign expectations."""
    return list(run_campaign(guard, cases).surprising)


def decision_matrix(
    guards: Mapping[str, ScopeGuard],
    cases: Iterable[ProbeCase] = DEFAULT_CASES,
) -> dict[str, dict[str, bool | None]]:
    """Compare multiple policies against exactly the same inputs."""
    frozen_cases = tuple(cases)
    matrix: dict[str, dict[str, bool | None]] = {}
    for label, guard in guards.items():
        matrix[label] = {
            result.case.name: result.allowed for result in probe_guard(guard, frozen_cases)
        }
    return matrix


def check_api_consistency(
    guard: ScopeGuard,
    cases: Iterable[ProbeCase] = DEFAULT_CASES,
) -> list[str]:
    """Check that check() and is_allowed() agree for every campaign input."""
    mismatches: list[str] = []
    for case in tuple(cases):
        expected_from_predicate = guard.is_allowed(case.target_ref)
        try:
            guard.check(case.target_ref)
        except ScopeViolation:
            expected_from_check = False
        except Exception as exc:
            mismatches.append(f"{case.name}: check raised {type(exc).__name__}: {exc}")
            continue
        else:
            expected_from_check = True

        if expected_from_check != expected_from_predicate:
            mismatches.append(
                f"{case.name}: check={expected_from_check} "
                f"is_allowed={expected_from_predicate}"
            )
    return mismatches
