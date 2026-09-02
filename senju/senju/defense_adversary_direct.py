"""Direct adversarial pressure against Senju's real defense codepaths.

Unlike mutation/copy harnesses, this suite imports the actual merged classes and
loads the actual repository policy/workflow files. It sends adversarial inputs
directly into those implementations and records what the real code accepts or
rejects.

It does not disable guards, alter production policy, write to third-party
systems, or perform live network I/O. Parser and policy pressure stops before
DNS/socket/open calls; artifact tests invoke the real artifact guard against
synthetic temporary build output; Autonomy pressure uses the real package and a
temporary queue/state directory without executing tournament or external I/O.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .authorized_assessment import EngagementError, EngagementManifest
from .autonomy import AutonomyEngine, AutonomyQueue, WorkItem, WorkItemStatus
from .external import ExternalContactError, ExternalContactPolicy, _parse_url
from .safety import ScopeGuard, default_lab_policy
from .scopeguard_adversary import DEFAULT_CASES, ProbeCase, probe_guard


@dataclass(frozen=True)
class Finding:
    layer: str
    case: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DirectReport:
    schema: str
    seed: int
    findings: tuple[Finding, ...]

    @property
    def weaknesses(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if not item.passed)

    def to_dict(self) -> dict[str, object]:
        layers: dict[str, dict[str, int]] = {}
        for item in self.findings:
            bucket = layers.setdefault(item.layer, {"checks": 0, "passed": 0, "weaknesses": 0})
            bucket["checks"] += 1
            bucket["passed" if item.passed else "weaknesses"] += 1
        return {
            "schema": self.schema,
            "seed": self.seed,
            "mode": "direct-real-codepaths",
            "summary": {
                "checks": len(self.findings),
                "passed": sum(1 for item in self.findings if item.passed),
                "weaknesses": len(self.weaknesses),
                "layers": layers,
            },
            "findings": [asdict(item) for item in self.findings],
        }


def _finding(layer: str, case: str, passed: bool, detail: str) -> Finding:
    return Finding(layer, case, bool(passed), detail)


# ScopeGuard: one real guard object receives the full adversarial corpus.
def _scope_cases(count: int, seed: int) -> tuple[ProbeCase, ...]:
    rng = random.Random(seed)
    bases = (
        "example.com", "EXAMPLE.COM", "https://example.com", "http://example.com",
        "ftp://example.com", "127.0.0.1", "127.1", "10.0.0.1", "169.254.1.1",
        "::1", "[::1]", "labnet:fixture", "LABNET:fixture", "SIM://fixture",
        "sim:/fixture", "sim%3A//fixture", "sim：//fixture",
    )
    wrappers: tuple[Callable[[str], str], ...] = (
        lambda v: v,
        lambda v: f" {v}",
        lambda v: f"{v} ",
        lambda v: f"\t{v}",
        lambda v: f"{v}\n",
        lambda v: f"//{v}",
        lambda v: f"{v}:443",
        lambda v: f"{v}/path",
        lambda v: f"{v}?q=1",
        lambda v: f"{v}#fragment",
        lambda v: f"{v}@other.invalid",
    )
    generated = tuple(
        ProbeCase(f"direct-{i:05d}", rng.choice(wrappers)(rng.choice(bases)), False)
        for i in range(max(0, count))
    )
    return DEFAULT_CASES + generated


def probe_scopeguard(*, count: int, seed: int) -> list[Finding]:
    real_guard = ScopeGuard(default_lab_policy())
    return [
        _finding("scopeguard", r.case.name, not r.surprising, r.detail)
        for r in probe_guard(real_guard, _scope_cases(count, seed))
    ]


# EngagementManifest: crafted JSON dictionaries go directly into the real parser.
def _manifest() -> dict[str, object]:
    return {
        "engagement_id": "direct-adversary",
        "owner": "local-test-owner",
        "authorization_reference": "synthetic://direct-adversary/local",
        "valid_from_utc": "2026-08-31T00:00:00+00:00",
        "valid_until_utc": "2026-09-01T00:00:00+00:00",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "root_snapshot"],
        "max_requests_per_target": 2,
        "max_rps": 1.0,
        "allow_http": False,
        "destructive": False,
    }


def probe_engagement() -> list[Finding]:
    cases: list[tuple[str, dict[str, object], bool]] = []
    cases.append(("valid", _manifest(), True))

    def altered(name: str, key: str, value: object, should_allow: bool = False) -> None:
        raw = json.loads(json.dumps(_manifest()))
        raw[key] = value
        cases.append((name, raw, should_allow))

    altered("empty-owner", "owner", "")
    altered("empty-authorization", "authorization_reference", "")
    altered("no-targets", "targets", [])
    altered("wildcard", "targets", [{"host": "*.example.com"}])
    altered("duplicate-target", "targets", [{"host": "example.com"}, {"host": "example.com"}])
    altered("unknown-check", "allowed_checks", ["reachability", "exploit"])
    altered("destructive", "destructive", True)
    altered("too-fast", "max_rps", 10)
    altered("string-false-http", "allow_http", "false")

    findings: list[Finding] = []
    for name, raw, should_allow in cases:
        try:
            EngagementManifest.from_dict(raw)
        except (EngagementError, TypeError, ValueError, AttributeError) as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        findings.append(_finding("engagement-json", name, allowed == should_allow, detail))

    now = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.timezone.utc)
    for name, start, end, should_allow in (
        ("active-window", "2026-08-31T00:00:00+00:00", "2026-09-01T00:00:00+00:00", True),
        ("expired-window", "2026-08-29T00:00:00+00:00", "2026-08-30T00:00:00+00:00", False),
        ("future-window", "2026-09-02T00:00:00+00:00", "2026-09-03T00:00:00+00:00", False),
    ):
        raw = _manifest()
        raw["valid_from_utc"] = start
        raw["valid_until_utc"] = end
        try:
            manifest = EngagementManifest.from_dict(raw)
            manifest.validate(now=now, enforce_window=True)
        except EngagementError as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        findings.append(_finding("engagement-json", name, allowed == should_allow, detail))
    return findings


# ExternalContact parser: actual parser only, deliberately before resolver/open.
def probe_external_contact() -> list[Finding]:
    policy = ExternalContactPolicy.from_hosts(["example.com"], allow_http=False)
    cases = (
        ("exact", "https://example.com/", True),
        ("uppercase", "https://EXAMPLE.COM/", True),
        ("trailing-dot", "https://example.com./", True),
        ("http", "http://example.com/", False),
        ("subdomain", "https://api.example.com/", False),
        ("suffix-lookalike", "https://example.com.invalid/", False),
        ("userinfo", "https://user@example.com/", False),
        ("password", "https://user:pass@example.com/", False),
        ("userinfo-confusion", "https://example.com@evil.invalid/", False),
        ("ftp", "ftp://example.com/", False),
        ("relative", "/x", False),
        ("bad-port", "https://example.com:abc/", False),
        ("out-of-range-port", "https://example.com:99999/", False),
        ("non-default-port", "https://example.com:444/", False),
    )
    out: list[Finding] = []
    for name, url, expected in cases:
        try:
            _parse_url(url, policy)
        except (ExternalContactError, TypeError, ValueError) as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        out.append(_finding("external-contact", name, allowed == expected, detail))
    return out


# Actual checked-in doctrine and workflow are loaded directly, not duplicated.
def probe_offense_first(repo_root: Path) -> list[Finding]:
    path = repo_root / "senju" / "OFFENSE_FIRST.md"
    if not path.is_file():
        return [_finding("offense-first", "present", False, f"missing: {path}")]
    text = path.read_text(encoding="utf-8")
    checks = {
        "authorized-lab-boundary": "owned-or-explicitly-authorized lab" in text,
        "third-party-boundary": "所有者または明示的なテスト権限" in text,
        "campaign-scope-boundary": "campaign scope" in text,
    }
    return [_finding("offense-first", name, ok, "present" if ok else "missing") for name, ok in checks.items()]


def probe_security_guard(repo_root: Path) -> list[Finding]:
    path = repo_root / ".github" / "workflows" / "security-guard.yml"
    if not path.is_file():
        return [_finding("security-guard-workflow", "present", False, f"missing: {path}")]
    text = path.read_text(encoding="utf-8")
    checks = {
        "read-only-permissions": "permissions:\n  contents: read" in text,
        "no-credential-persistence": "persist-credentials: false" in text,
        "secret-file-block": "Block tracked secret files" in text,
        "secret-material-block": "Block obvious credential material in tracked source" in text,
        "workflow-policy": "workflow_policy_entrypoint.py" in text,
        "reality-gate": "reality_gate.py" in text,
        "remote-shell-block": "Block remote shell execution patterns" in text,
        "untrusted-interpolation-block": "Block direct interpolation of untrusted event text" in text,
        "no-pull-request-target": "pull_request_target:" not in text,
        "no-write-all": "permissions: write-all" not in text,
    }
    return [_finding("security-guard-workflow", name, ok, "intact" if ok else "missing/unsafe") for name, ok in checks.items()]


# Actual artifact_guard.py executable receives adversarial temporary artifacts.
def _artifact_case(guard: Path, files: Mapping[str, str]) -> tuple[int, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="senju-direct-artifact-") as tmp:
        root = Path(tmp)
        dist = root / "dist"
        dist.mkdir()
        for rel, content in files.items():
            target = dist / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        report = root / "report.json"
        proc = subprocess.run(
            [sys.executable, str(guard), str(dist), "--json", str(report)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        payload = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        return proc.returncode, payload


def probe_artifact_guard(repo_root: Path) -> list[Finding]:
    guard = repo_root / "scripts" / "security" / "artifact_guard.py"
    if not guard.is_file():
        return [_finding("artifact-guard", "present", False, f"missing: {guard}")]
    fake_key = "sk-" + "A" * 24
    cases = (
        ("clean", {"index.html": '<script src="https://example.com/app.js"></script>'}, True, None),
        ("source-map", {"app.js.map": "{}"}, False, "artifact.source-map"),
        ("mixed-content", {"index.html": '<script src="http://example.com/a.js"></script>'}, False, "artifact.mixed-content"),
        ("localhost", {"app.js": 'fetch("http://localhost:3000/api")'}, False, "artifact.localhost-reference"),
        ("source-map-ref", {"app.js": "//# sourceMappingURL=app.js.map"}, False, "artifact.source-map-reference"),
        ("synthetic-secret", {"config.json": json.dumps({"token": fake_key})}, False, "artifact.secret.openai-key"),
    )
    out: list[Finding] = []
    for name, files, should_pass, expected_rule in cases:
        try:
            code, payload = _artifact_case(guard, files)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            out.append(_finding("artifact-guard", name, False, f"runner error: {exc}"))
            continue
        rules = {str(x.get("rule")) for x in payload.get("findings", []) if isinstance(x, dict)}
        actual_pass = code == 0 and payload.get("status") == "pass"
        passed = actual_pass if should_pass else (code != 0 and expected_rule in rules)
        out.append(_finding("artifact-guard", name, passed, f"exit={code}; rules={sorted(rules)}"))
    return out


# Actual Autonomy package: instantiate real queue/engine in temporary state.
def probe_autonomy(repo_root: Path) -> list[Finding]:
    out: list[Finding] = []
    engine_path = repo_root / "senju" / "senju" / "autonomy" / "engine.py"
    queue_path = repo_root / "senju" / "senju" / "autonomy" / "queue.py"
    out.append(_finding("autonomy-engine", "engine-real-file", engine_path.is_file(), str(engine_path)))
    out.append(_finding("autonomy-engine", "queue-real-file", queue_path.is_file(), str(queue_path)))

    with tempfile.TemporaryDirectory(prefix="senju-direct-autonomy-") as tmp:
        state = Path(tmp)
        engine = AutonomyEngine(state)
        out.append(_finding("autonomy-engine", "real-engine-instantiation", isinstance(engine, AutonomyEngine), f"seed_items={len(engine.queue._items)}"))

        queue = AutonomyQueue(state / "pressure_queue.json")
        first = WorkItem("direct-1", "same hypothesis", "resilience", 0.8, parameters={"x": 1})
        duplicate = WorkItem("direct-2", "same hypothesis", "resilience", 0.8, parameters={"x": 1})
        first_ok = queue.enqueue(first)
        duplicate_ok = queue.enqueue(duplicate)
        out.append(_finding("autonomy-engine", "dedup", first_ok and not duplicate_ok, f"first={first_ok}; duplicate={duplicate_ok}"))

        over_budget = WorkItem("direct-budget", "over budget", "resilience", 0.9, cost_budget_matches=10000)
        queue.enqueue(over_budget)
        selected = queue.select_next(budget_matches=100)
        out.append(_finding("autonomy-engine", "budget-gate", selected is None, f"selected={getattr(selected, 'item_id', None)}"))

        invalid_scope = WorkItem("direct-scope", "unknown authority", "threat_intel", 0.5, authority_scope="totally_unknown")
        accepted_scope = queue.enqueue(invalid_scope)
        out.append(_finding("autonomy-engine", "unknown-authority-scope-rejected", not accepted_scope, f"accepted={accepted_scope}"))

        negative_value = WorkItem("direct-negative", "negative expected value", "resilience", -1.0)
        accepted_negative = queue.enqueue(negative_value)
        out.append(_finding("autonomy-engine", "negative-expected-value-rejected", not accepted_negative, f"accepted={accepted_negative}"))

        empty_hypothesis = WorkItem("direct-empty", "", "resilience", 0.5)
        accepted_empty = queue.enqueue(empty_hypothesis)
        out.append(_finding("autonomy-engine", "empty-hypothesis-rejected", not accepted_empty, f"accepted={accepted_empty}"))

        bad_status = WorkItem("direct-status", "bad status", "resilience", 0.5, status="unknown-state")
        accepted_status = queue.enqueue(bad_status)
        out.append(_finding("autonomy-engine", "unknown-status-rejected", not accepted_status, f"accepted={accepted_status}"))

        retry = WorkItem("direct-retry", "retry gate", "resilience", 0.5, status=WorkItemStatus.FAILED.value, attempt_count=3, max_retries=2)
        queue.enqueue(retry)
        picked = queue.select_next(budget_matches=5000)
        out.append(_finding("autonomy-engine", "retry-limit", picked is None or picked.item_id != retry.item_id, f"selected={getattr(picked, 'item_id', None)}"))
    return out


def run_direct(repo_root: Path | None = None, *, scope_cases: int = 4096, seed: int = 26003) -> DirectReport:
    root = repo_root or Path(__file__).resolve().parents[2]
    findings: list[Finding] = []
    findings.extend(probe_scopeguard(count=scope_cases, seed=seed))
    findings.extend(probe_engagement())
    findings.extend(probe_external_contact())
    findings.extend(probe_offense_first(root))
    findings.extend(probe_security_guard(root))
    findings.extend(probe_artifact_guard(root))
    findings.extend(probe_autonomy(root))
    return DirectReport("senju-direct-defense-adversary/v3", seed, tuple(findings))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run direct adversarial pressure against real Senju defense codepaths")
    parser.add_argument("--json", dest="output", type=Path)
    parser.add_argument("--scope-cases", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=26003)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_direct(scope_cases=max(0, args.scope_cases), seed=args.seed)
    payload = report.to_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps(payload["summary"], ensure_ascii=False))
    else:
        print(rendered, end="")
    return 1 if args.strict and report.weaknesses else 0


if __name__ == "__main__":
    raise SystemExit(main())
