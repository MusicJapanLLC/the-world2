"""Live-bound opposition force for Senju guard surfaces.

This module deliberately targets the real repository guard implementations rather than
surrogate copies. It verifies source-file bindings before running deterministic and
high-pressure adversarial campaigns. Probes remain local/non-destructive: network
transports are faked, document mutations are in-memory, and queue/artifact probes use
temporary fixtures.
"""
from __future__ import annotations

import inspect
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .authorized_assessment import EngagementError, EngagementManifest
from .autonomy import AutonomyEngine, AutonomyQueue, WorkItem
from .external import ExternalContactClient, ExternalContactError, ExternalContactPolicy
from .multiguard_adversary import (
    ARTIFACT_GUARD_PATH,
    OFFENSE_FIRST_PATH,
    REPO_ROOT,
    SECURITY_GUARD_PATH,
    SENJU_ROOT,
    TARGETS,
    MultiGuardReport,
    build_campaign,
    run_campaign,
)
from .safety import ScopeGuard, ScopeViolation, default_lab_policy


@dataclass(frozen=True)
class LiveBinding:
    target: str
    expected_path: str
    observed_path: str
    matched: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "expected_path": self.expected_path,
            "observed_path": self.observed_path,
            "matched": self.matched,
        }


@dataclass(frozen=True)
class PressureResult:
    name: str
    attempts: int
    expected_rejections: int
    observed_rejections: int
    unexpected_accepts: int = 0
    unexpected_exceptions: int = 0
    side_effect_calls: int = 0

    @property
    def passed(self) -> bool:
        return (
            self.observed_rejections == self.expected_rejections
            and self.unexpected_accepts == 0
            and self.unexpected_exceptions == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "attempts": self.attempts,
            "expected_rejections": self.expected_rejections,
            "observed_rejections": self.observed_rejections,
            "unexpected_accepts": self.unexpected_accepts,
            "unexpected_exceptions": self.unexpected_exceptions,
            "side_effect_calls": self.side_effect_calls,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class OppositionForceReport:
    bindings: tuple[LiveBinding, ...]
    campaign: MultiGuardReport
    pressure: tuple[PressureResult, ...]

    @property
    def surrogate_count(self) -> int:
        return sum(not binding.matched for binding in self.bindings)

    @property
    def pressure_attempts(self) -> int:
        return sum(result.attempts for result in self.pressure)

    @property
    def pressure_failures(self) -> int:
        return sum(not result.passed for result in self.pressure)

    @property
    def passed(self) -> bool:
        return (
            self.surrogate_count == 0
            and self.campaign.passed
            and self.pressure_failures == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "senju-live-opposition-force/v2",
            "mode": "real-implementation-bindings+near-failure-pressure",
            "targets": list(TARGETS),
            "binding_count": len(self.bindings),
            "surrogate_count": self.surrogate_count,
            "pressure_attempts": self.pressure_attempts,
            "pressure_failures": self.pressure_failures,
            "passed": self.passed,
            "bindings": [binding.to_dict() for binding in self.bindings],
            "campaign": self.campaign.to_dict(),
            "pressure": [result.to_dict() for result in self.pressure],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _binding_for_object(target: str, obj: object, expected: Path) -> LiveBinding:
    source = inspect.getsourcefile(obj) or inspect.getfile(obj)
    observed = Path(source).resolve() if source else Path("<unknown>")
    expected_resolved = expected.resolve()
    return LiveBinding(
        target=target,
        expected_path=_relative(expected_resolved),
        observed_path=(
            _relative(observed)
            if observed.is_absolute() and REPO_ROOT.resolve() in observed.parents
            else str(observed)
        ),
        matched=observed == expected_resolved,
    )


def _binding_for_file(target: str, observed: Path, expected: Path) -> LiveBinding:
    observed_resolved = observed.resolve()
    expected_resolved = expected.resolve()
    return LiveBinding(
        target=target,
        expected_path=_relative(expected_resolved),
        observed_path=_relative(observed_resolved),
        matched=observed_resolved == expected_resolved and observed_resolved.is_file(),
    )


def verify_live_bindings() -> tuple[LiveBinding, ...]:
    """Prove the opposition force is wired to production guard sources, not copies."""
    bindings = (
        _binding_for_object("scopeguard", ScopeGuard, SENJU_ROOT / "senju" / "safety.py"),
        _binding_for_file("offense-first", OFFENSE_FIRST_PATH, SENJU_ROOT / "OFFENSE_FIRST.md"),
        _binding_for_object(
            "engagement-json",
            EngagementManifest,
            SENJU_ROOT / "senju" / "authorized_assessment.py",
        ),
        _binding_for_object(
            "external-contact",
            ExternalContactClient,
            SENJU_ROOT / "senju" / "external.py",
        ),
        _binding_for_file(
            "security-guard",
            SECURITY_GUARD_PATH,
            REPO_ROOT / ".github" / "workflows" / "security-guard.yml",
        ),
        _binding_for_file(
            "artifact-guard",
            ARTIFACT_GUARD_PATH,
            REPO_ROOT / "scripts" / "security" / "artifact_guard.py",
        ),
        _binding_for_object(
            "autonomy-engine",
            AutonomyEngine,
            SENJU_ROOT / "senju" / "autonomy" / "engine.py",
        ),
    )
    assert tuple(binding.target for binding in bindings) == TARGETS
    return bindings


def _scopeguard_saturation() -> PressureResult:
    guard = ScopeGuard(default_lab_policy())
    attempts = 20_000
    rejected = 0
    unexpected = 0
    for i in range(attempts):
        ref = f"public-{i}.example"
        try:
            guard.check(ref)
        except ScopeViolation:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="scopeguard-20k-rejection-saturation",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
    )


def _scopeguard_long_control_storm() -> PressureResult:
    guard = ScopeGuard(default_lab_policy())
    attempts = 2_000
    rejected = 0
    unexpected = 0
    payload = "sim://" + ("a" * 4096) + "\x00"
    for _ in range(attempts):
        try:
            guard.check(payload)
        except ScopeViolation:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="scopeguard-long-control-storm",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
    )


def _engagement_type_storm() -> PressureResult:
    attempts = 8_000
    rejected = 0
    unexpected = 0
    baseline = {
        "owner": "pressure-test",
        "authorization_reference": "local-fixture",
        "targets": [{"host": "example.com"}],
        "allowed_checks": ["reachability"],
    }
    mutations = (
        {"max_requests_per_target": "8"},
        {"max_rps": "2.0"},
        {"allow_http": "false"},
        {"destructive": "false"},
        {"targets": "example.com"},
        {"targets": ["example.com"]},
        {"allowed_checks": "reachability"},
        {"max_rps": float("nan")},
    )
    for i in range(attempts):
        raw = dict(baseline)
        raw.update(mutations[i % len(mutations)])
        try:
            EngagementManifest.from_dict(raw)
        except EngagementError:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="engagement-8k-type-storm",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
    )


def _external_timeout_storm() -> PressureResult:
    class CountingTimeoutOpener:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, request, *, timeout: float):  # noqa: ANN001
            self.calls += 1
            raise TimeoutError("injected timeout")

    attempts = 500
    rejected = 0
    unexpected = 0
    opener = CountingTimeoutOpener()
    policy = ExternalContactPolicy.from_hosts(["example.com"], retries=5)
    client = ExternalContactClient(
        policy,
        resolver=lambda host, port: ("93.184.216.34",),
        opener=opener,
        sleeper=lambda seconds: None,
    )
    for _ in range(attempts):
        try:
            client.contact("https://example.com/")
        except ExternalContactError:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="external-500-timeout-storm-6-attempts-each",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
        side_effect_calls=opener.calls,
    )


def _external_oversize_response_storm() -> PressureResult:
    class OversizeResponse:
        status = 200
        headers: dict[str, str] = {}

        def __init__(self, size: int) -> None:
            self.size = size

        def read(self, limit: int = -1) -> bytes:
            return b"x" * self.size

        def close(self) -> None:
            return None

    class CountingOpener:
        def __init__(self, size: int) -> None:
            self.calls = 0
            self.size = size

        def __call__(self, request, *, timeout: float):  # noqa: ANN001
            self.calls += 1
            return OversizeResponse(self.size)

    attempts = 300
    rejected = 0
    unexpected = 0
    policy = ExternalContactPolicy.from_hosts(["example.com"], max_response_bytes=1024, retries=0)
    opener = CountingOpener(policy.max_response_bytes + 1)
    client = ExternalContactClient(
        policy,
        resolver=lambda host, port: ("93.184.216.34",),
        opener=opener,
        sleeper=lambda seconds: None,
    )
    for _ in range(attempts):
        try:
            client.contact("https://example.com/")
        except ExternalContactError:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="external-300-oversize-response-storm",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
        side_effect_calls=opener.calls,
    )


def _autonomy_corrupt_state_storm() -> PressureResult:
    attempts = 1_000
    rejected = 0
    unexpected = 0
    corrupt_values = (
        "{",
        "[]",
        '{"items": "not-a-list"}',
        '{"items": [null]}',
        '{"items": [{"item_id": "x"}]}',
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "queue.json"
        for i in range(attempts):
            path.write_text(corrupt_values[i % len(corrupt_values)], encoding="utf-8")
            try:
                queue = AutonomyQueue(path)
                if queue.pending_count() == 0 and queue.completed_count() == 0:
                    rejected += 1
            except Exception:
                unexpected += 1
    return PressureResult(
        name="autonomy-1k-corrupt-state-storm",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
    )


def _autonomy_invalid_workitem_storm() -> PressureResult:
    attempts = 8_000
    rejected = 0
    unexpected = 0
    variants = (
        {"expected_value": 1.1},
        {"cost_budget_matches": 0},
        {"runtime_seconds_budget": 0.0},
        {"authority_scope": "arbitrary-admin"},
        {"max_retries": 11},
        {"parameters": {"population": 257}},
        {"parameters": {"matches": 5001}},
        {"parameters": {"mutation_rate": 1.1}},
    )
    for i in range(attempts):
        kwargs = {
            "item_id": f"pressure-{i}",
            "hypothesis": "pressure-test",
            "category": "test",
            "expected_value": 0.5,
        }
        kwargs.update(variants[i % len(variants)])
        try:
            WorkItem(**kwargs)
        except ValueError:
            rejected += 1
        except Exception:
            unexpected += 1
    return PressureResult(
        name="autonomy-8k-invalid-workitem-storm",
        attempts=attempts,
        expected_rejections=attempts,
        observed_rejections=rejected,
        unexpected_accepts=attempts - rejected - unexpected,
        unexpected_exceptions=unexpected,
    )


def run_pressure_campaign() -> tuple[PressureResult, ...]:
    """Drive real guards toward failure without weakening or bypassing them."""
    return (
        _scopeguard_saturation(),
        _scopeguard_long_control_storm(),
        _engagement_type_storm(),
        _external_timeout_storm(),
        _external_oversize_response_storm(),
        _autonomy_corrupt_state_storm(),
        _autonomy_invalid_workitem_storm(),
    )


def run_live_opposition_force() -> OppositionForceReport:
    """Run full deterministic and near-failure campaigns against real sources."""
    bindings = verify_live_bindings()
    campaign = run_campaign(build_campaign())
    pressure = run_pressure_campaign()
    return OppositionForceReport(bindings=bindings, campaign=campaign, pressure=pressure)
