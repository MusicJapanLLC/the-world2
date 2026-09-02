"""Live adversary loop for the active Senju guard surfaces.

This runner imports and executes the real guard implementations from the checked-out
repository. It also reads the active policy/workflow files in-place on every round.
It never disables a guard, writes production policy, or performs live outbound contact.
Where a side-effecting component needs an input, the real implementation is exercised
against a disposable local fixture so production state is not modified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .authorized_assessment import EngagementError, EngagementManifest
from .autonomy import AutonomyQueue, WorkItem
from .defense_adversary_team_v2 import (
    audit_offense_text,
    audit_security_guard_text,
    run_v2,
)
from .external import ExternalContactError, ExternalContactPolicy, _parse_url
from .safety import ScopeGuard, ScopeViolation, default_lab_policy


LIVE_LAYERS = (
    "scopeguard",
    "offense-first",
    "engagement-json",
    "external-contact",
    "security-guard",
    "artifact-guard",
    "autonomy-engine",
)


@dataclass(frozen=True)
class LiveSurfaceResult:
    layer: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RoundResult:
    round_index: int
    seed: int
    started_at_utc: str
    completed_at_utc: str
    checks: int
    weaknesses: int
    live_checks: int
    live_weaknesses: int
    crashed: bool
    live_surfaces: tuple[LiveSurfaceResult, ...]
    crash_detail: str = ""


@dataclass(frozen=True)
class LiveReport:
    schema: str
    rounds: tuple[RoundResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "execution_mode": "active-codepath",
            "live_layers": list(LIVE_LAYERS),
            "summary": {
                "rounds": len(self.rounds),
                "checks": sum(r.checks for r in self.rounds),
                "weaknesses": sum(r.weaknesses for r in self.rounds),
                "live_checks": sum(r.live_checks for r in self.rounds),
                "live_weaknesses": sum(r.live_weaknesses for r in self.rounds),
                "crashes": sum(1 for r in self.rounds if r.crashed),
            },
            "rounds": [asdict(r) for r in self.rounds],
        }


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _surface(layer: str, passed: bool, detail: str) -> LiveSurfaceResult:
    return LiveSurfaceResult(layer=layer, passed=bool(passed), detail=detail)


def _check_scopeguard() -> LiveSurfaceResult:
    guard = ScopeGuard(default_lab_policy())
    guard.check("sim://live-adversary-liveness")
    try:
        guard.check("sim://live-adversary\x00")
    except ScopeViolation as exc:
        return _surface("scopeguard", True, f"active implementation rejected malformed ref: {exc}")
    return _surface("scopeguard", False, "active implementation accepted NUL-suffixed simulated ref")


def _check_offense_first(root: Path) -> LiveSurfaceResult:
    path = root / "senju" / "OFFENSE_FIRST.md"
    if not path.is_file():
        return _surface("offense-first", False, f"active policy missing: {path}")
    problems = audit_offense_text(path.read_text(encoding="utf-8"))
    return _surface(
        "offense-first",
        not problems,
        "; ".join(problems) if problems else "active policy contract intact",
    )


def _engagement_payload(now: dt.datetime) -> dict[str, object]:
    return {
        "engagement_id": "live-adversary-real-surface",
        "owner": "local-live-adversary",
        "authorization_reference": "synthetic://live-adversary/no-contact",
        "valid_from_utc": (now - dt.timedelta(minutes=5)).isoformat(),
        "valid_until_utc": (now + dt.timedelta(minutes=5)).isoformat(),
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "root_snapshot"],
        "max_requests_per_target": 2,
        "max_rps": 1.0,
        "allow_http": False,
        "destructive": False,
    }


def _check_engagement() -> LiveSurfaceResult:
    now = dt.datetime.now(dt.timezone.utc)
    payload = _engagement_payload(now)
    try:
        EngagementManifest.from_dict(payload).validate(now=now, enforce_window=True)
    except Exception as exc:  # noqa: BLE001 - live telemetry
        return _surface("engagement-json", False, f"valid active manifest rejected: {type(exc).__name__}: {exc}")

    malformed = dict(payload)
    malformed["allow_http"] = "false"
    malformed["targets"] = [{"host": "example.com", "scheme": "http", "base_path": "/"}]
    try:
        EngagementManifest.from_dict(malformed)
    except (EngagementError, TypeError, ValueError):
        return _surface("engagement-json", True, "active parser accepted valid manifest and rejected wrong JSON types")
    return _surface("engagement-json", False, "active parser accepted string-shaped boolean authority input")


def _check_external_contact() -> LiveSurfaceResult:
    policy = ExternalContactPolicy.from_hosts(["example.com"], allow_http=False)
    host, port = _parse_url("https://example.com/", policy)
    if (host, port) != ("example.com", 443):
        return _surface("external-contact", False, f"unexpected active parser result: {(host, port)!r}")
    for invalid in (
        "https://example.com.invalid/",
        "https://example.com:444/",
        "https://user@example.com/",
    ):
        try:
            _parse_url(invalid, policy)
        except (ExternalContactError, TypeError, ValueError):
            continue
        return _surface("external-contact", False, f"active parser accepted disallowed authority: {invalid}")
    return _surface("external-contact", True, "active parser enforced exact host, port and userinfo boundaries")


def _check_security_guard(root: Path) -> LiveSurfaceResult:
    path = root / ".github" / "workflows" / "security-guard.yml"
    if not path.is_file():
        return _surface("security-guard", False, f"active workflow missing: {path}")
    problems = audit_security_guard_text(path.read_text(encoding="utf-8"))
    return _surface(
        "security-guard",
        not problems,
        "; ".join(problems) if problems else "active workflow invariants intact",
    )


def _check_artifact_guard(root: Path) -> LiveSurfaceResult:
    guard = root / "scripts" / "security" / "artifact_guard.py"
    if not guard.is_file():
        return _surface("artifact-guard", False, f"active guard missing: {guard}")
    with tempfile.TemporaryDirectory(prefix="senju-live-artifact-") as tmp:
        base = Path(tmp)
        clean = base / "clean"
        clean.mkdir()
        (clean / "index.html").write_text('<a href="https://example.com/">ok</a>\n', encoding="utf-8")
        clean_report = base / "clean.json"
        clean_run = subprocess.run(
            [sys.executable, str(guard), str(clean), "--json", str(clean_report)],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if clean_run.returncode != 0:
            return _surface("artifact-guard", False, f"active guard rejected clean fixture: {clean_run.stderr[-300:]}")

        flagged = base / "flagged"
        flagged.mkdir()
        (flagged / "bundle.js.map").write_text("{}\n", encoding="utf-8")
        flagged_report = base / "flagged.json"
        flagged_run = subprocess.run(
            [sys.executable, str(guard), str(flagged), "--json", str(flagged_report)],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if flagged_run.returncode == 0:
            return _surface("artifact-guard", False, "active guard failed to reject source-map exposure fixture")
    return _surface("artifact-guard", True, "active artifact guard executed and rejected a known exposure")


def _check_autonomy() -> LiveSurfaceResult:
    with tempfile.TemporaryDirectory(prefix="senju-live-autonomy-") as tmp:
        queue = AutonomyQueue(Path(tmp) / "queue.json")
        item = WorkItem(
            item_id="live-valid",
            hypothesis="validate active autonomy queue",
            category="test",
            expected_value=0.5,
            cost_budget_matches=20,
            runtime_seconds_budget=1.0,
            authority_scope="none",
        )
        if not queue.enqueue(item):
            return _surface("autonomy-engine", False, "active queue unexpectedly rejected valid work item")
        selected = queue.select_next(budget_matches=20)
        if selected is None or selected.item_id != "live-valid":
            return _surface("autonomy-engine", False, "active queue failed bounded selection")
        try:
            WorkItem(
                item_id="live-invalid",
                hypothesis="invalid authority must fail closed",
                category="test",
                expected_value=0.5,
                authority_scope="arbitrary-admin",
            )
        except (TypeError, ValueError):
            return _surface("autonomy-engine", True, "active queue accepted bounded item and rejected invalid authority")
    return _surface("autonomy-engine", False, "active WorkItem accepted unknown authority scope")


def _live_surface_checks(root: Path) -> tuple[LiveSurfaceResult, ...]:
    checks = (
        lambda: _check_scopeguard(),
        lambda: _check_offense_first(root),
        lambda: _check_engagement(),
        lambda: _check_external_contact(),
        lambda: _check_security_guard(root),
        lambda: _check_artifact_guard(root),
        lambda: _check_autonomy(),
    )
    results: list[LiveSurfaceResult] = []
    for layer, check in zip(LIVE_LAYERS, checks, strict=True):
        try:
            result = check()
        except Exception as exc:  # noqa: BLE001 - one surface must not hide the rest
            result = _surface(layer, False, f"live check crashed: {type(exc).__name__}: {exc}")
        results.append(result)
    return tuple(results)


def run_live_loop(
    *,
    repo_root: Path | None = None,
    rounds: int = 8,
    scope_cases: int = 1024,
    seed: int = 31001,
    delay_seconds: float = 0.0,
) -> LiveReport:
    root = (repo_root or _repo_root()).resolve()
    results: list[RoundResult] = []
    for index in range(max(1, rounds)):
        started = _utcnow()
        round_seed = seed + index * 7919
        checks = 0
        weaknesses = 0
        live_checks = 0
        live_weaknesses = 0
        crashed = False
        detail = ""
        surfaces: tuple[LiveSurfaceResult, ...] = ()
        try:
            report = run_v2(root, scope_cases=max(0, scope_cases), seed=round_seed)
            summary = report.to_dict()["summary"]
            checks = int(summary["checks"])
            weaknesses = int(summary["weaknesses"])
            surfaces = _live_surface_checks(root)
            live_checks = len(surfaces)
            live_weaknesses = sum(not surface.passed for surface in surfaces)
            checks += live_checks
            weaknesses += live_weaknesses
        except Exception as exc:  # noqa: BLE001 - crash telemetry is the point
            crashed = True
            detail = f"{type(exc).__name__}: {exc}"
        results.append(
            RoundResult(
                round_index=index + 1,
                seed=round_seed,
                started_at_utc=started,
                completed_at_utc=_utcnow(),
                checks=checks,
                weaknesses=weaknesses,
                live_checks=live_checks,
                live_weaknesses=live_weaknesses,
                crashed=crashed,
                live_surfaces=surfaces,
                crash_detail=detail,
            )
        )
        if delay_seconds > 0 and index + 1 < rounds:
            time.sleep(min(max(delay_seconds, 0.0), 60.0))
    return LiveReport("senju-live-guard-adversary/v2", tuple(results))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pressure all active Senju guard codepaths and live policy surfaces")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--scope-cases", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=31001)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--json", dest="output", type=Path)
    parser.add_argument("--fail-on-crash", action="store_true")
    parser.add_argument("--fail-on-weakness", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_live_loop(
        rounds=max(1, args.rounds),
        scope_cases=max(0, args.scope_cases),
        seed=args.seed,
        delay_seconds=args.delay_seconds,
    )
    payload = report.to_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    crashes = int(payload["summary"]["crashes"])
    weaknesses = int(payload["summary"]["weaknesses"])
    if args.fail_on_crash and crashes:
        return 1
    if args.fail_on_weakness and weaknesses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
