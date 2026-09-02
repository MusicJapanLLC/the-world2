"""Defense Adversary Suite V2 for Senju guard layers.

Local-only adversarial pressure for policy, parser, workflow, artifact and
Autonomy Engine boundaries. The suite performs no live network contact and
never disables or mutates production guards.
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
class AdversaryReport:
    schema: str
    seed: int
    findings: tuple[Finding, ...]

    @property
    def weaknesses(self) -> tuple[Finding, ...]:
        return tuple(x for x in self.findings if not x.passed)

    def to_dict(self) -> dict[str, object]:
        layers: dict[str, dict[str, int]] = {}
        for item in self.findings:
            bucket = layers.setdefault(item.layer, {"checks": 0, "passed": 0, "weaknesses": 0})
            bucket["checks"] += 1
            bucket["passed" if item.passed else "weaknesses"] += 1
        return {
            "schema": self.schema,
            "seed": self.seed,
            "summary": {
                "checks": len(self.findings),
                "passed": sum(x.passed for x in self.findings),
                "weaknesses": len(self.weaknesses),
                "layers": layers,
            },
            "findings": [asdict(x) for x in self.findings],
        }


def _result(layer: str, case: str, passed: bool, detail: str) -> Finding:
    return Finding(layer, case, bool(passed), detail)


# ScopeGuard -----------------------------------------------------------------
def _scope_mutations(count: int, seed: int) -> tuple[ProbeCase, ...]:
    rng = random.Random(seed)
    bases = (
        "example.com", "EXAMPLE.COM", "https://example.com", "http://example.com",
        "ftp://example.com", "127.0.0.1", "127.1", "10.0.0.1", "169.254.1.1",
        "::1", "[::1]", "labnet:fixture", "LABNET:fixture", "SIM://fixture",
        "sim:/fixture", "sim%3A//fixture", "sim：//fixture",
    )
    wrappers: tuple[Callable[[str], str], ...] = (
        lambda v: v,
        lambda v: f" {v}", lambda v: f"{v} ", lambda v: f"\t{v}", lambda v: f"{v}\n",
        lambda v: f"//{v}", lambda v: f"{v}:443", lambda v: f"{v}/path",
        lambda v: f"{v}?q=1", lambda v: f"{v}#fragment", lambda v: f"{v}@other.invalid",
    )
    return tuple(
        ProbeCase(f"v2-fuzz-{i:05d}", rng.choice(wrappers)(rng.choice(bases)), False)
        for i in range(max(0, count))
    )


def probe_scopeguard_v2(*, count: int = 4096, seed: int = 26002) -> list[Finding]:
    cases = DEFAULT_CASES + _scope_mutations(count, seed)
    return [
        _result("scopeguard", r.case.name, not r.surprising, r.detail)
        for r in probe_guard(ScopeGuard(default_lab_policy()), cases)
    ]


# ExternalContactClient -------------------------------------------------------
def probe_external_contact_v2() -> list[Finding]:
    policy = ExternalContactPolicy.from_hosts(["example.com"], allow_http=False)
    cases: tuple[tuple[str, str, bool], ...] = (
        ("exact-https", "https://example.com/", True),
        ("uppercase-host", "https://EXAMPLE.COM/", True),
        ("trailing-dot", "https://example.com./", True),
        ("path-query-fragment", "https://example.com/a?b=1#c", True),
        ("http-disabled", "http://example.com/", False),
        ("subdomain", "https://api.example.com/", False),
        ("suffix-lookalike", "https://example.com.invalid/", False),
        ("prefix-lookalike", "https://notexample.com/", False),
        ("userinfo", "https://user@example.com/", False),
        ("password", "https://user:pass@example.com/", False),
        ("userinfo-host-confusion", "https://example.com@evil.invalid/", False),
        ("ftp", "ftp://example.com/", False),
        ("file", "file:///tmp/x", False),
        ("javascript", "javascript:alert(1)", False),
        ("missing-scheme", "//example.com/path", False),
        ("missing-host", "https:///path", False),
        ("relative", "/relative/path", False),
        ("empty", "", False),
        ("bad-port-alpha", "https://example.com:abc/", False),
        ("bad-port-range", "https://example.com:99999/", False),
        ("ipv4-not-allowlisted", "https://127.0.0.1/", False),
        ("ipv6-not-allowlisted", "https://[::1]/", False),
        ("encoded-at-host", "https://%40example.com/", False),
        # Defensive expectation: an authority scope should bind port as well as host.
        ("non-default-port", "https://example.com:444/", False),
    )
    out: list[Finding] = []
    for name, url, should_allow in cases:
        try:
            _parse_url(url, policy)
        except (ExternalContactError, TypeError, ValueError) as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        out.append(_result("external-contact", name, allowed == should_allow, detail))
    return out


# Engagement JSON -------------------------------------------------------------
def _engagement_baseline() -> dict[str, object]:
    return {
        "engagement_id": "v2-local-synthetic",
        "owner": "local-test-owner",
        "authorization_reference": "synthetic://defense-adversary/local-only",
        "valid_from_utc": "2026-08-31T00:00:00+00:00",
        "valid_until_utc": "2026-09-01T00:00:00+00:00",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "root_snapshot"],
        "max_requests_per_target": 2,
        "max_rps": 1.0,
        "allow_http": False,
        "destructive": False,
    }


def _copy_manifest() -> dict[str, object]:
    return json.loads(json.dumps(_engagement_baseline()))


def probe_engagement_v2() -> list[Finding]:
    cases: list[tuple[str, Mapping[str, Any], bool]] = [("valid-baseline", _copy_manifest(), True)]
    standing = _copy_manifest()
    standing.update(engagement_id="", valid_from_utc="", valid_until_utc="")
    cases.append(("standing-authority-derived-id", standing, True))

    def simple(name: str, key: str, value: object, allowed: bool = False) -> None:
        raw = _copy_manifest(); raw[key] = value; cases.append((name, raw, allowed))

    simple("owner-empty", "owner", "")
    simple("authorization-empty", "authorization_reference", "")
    simple("targets-empty", "targets", [])
    simple("targets-wrong-type", "targets", {"host": "example.com"})
    simple("checks-wrong-type", "allowed_checks", "reachability")
    simple("checks-empty", "allowed_checks", [])
    simple("unknown-check", "allowed_checks", ["reachability", "exploit"])
    simple("request-budget-zero", "max_requests_per_target", 0)
    simple("request-budget-high", "max_requests_per_target", 9)
    simple("rps-zero", "max_rps", 0)
    simple("rps-high", "max_rps", 2.1)
    simple("destructive", "destructive", True)
    simple("partial-window", "valid_until_utc", "")
    simple("bad-start-format", "valid_from_utc", "not-a-date")
    simple("timezone-missing", "valid_from_utc", "2026-08-31T00:00:00")

    for name, targets in (
        ("wildcard-host", [{"host": "*.example.com"}]),
        ("duplicate-host", [{"host": "example.com"}, {"host": "example.com"}]),
        ("http-without-optin", [{"host": "example.com", "scheme": "http"}]),
        ("unsupported-scheme", [{"host": "example.com", "scheme": "ftp"}]),
        ("fragment-in-path", [{"host": "example.com", "base_path": "/x#frag"}]),
        ("relative-base-path", [{"host": "example.com", "base_path": "relative"}]),
    ):
        raw = _copy_manifest(); raw["targets"] = targets; cases.append((name, raw, False))
    reversed_window = _copy_manifest()
    reversed_window.update(valid_from_utc="2026-09-01T00:00:00+00:00", valid_until_utc="2026-08-31T00:00:00+00:00")
    cases.append(("reversed-window", reversed_window, False))
    string_false = _copy_manifest()
    string_false["allow_http"] = "false"
    string_false["targets"] = [{"host": "example.com", "scheme": "http"}]
    cases.append(("string-false-http-coercion", string_false, False))

    out: list[Finding] = []
    for name, raw, should_allow in cases:
        try:
            EngagementManifest.from_dict(raw)
        except (EngagementError, TypeError, ValueError, AttributeError) as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        out.append(_result("engagement-json", name, allowed == should_allow, detail))

    now = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.timezone.utc)
    windows = (
        ("active-window", "2026-08-31T00:00:00+00:00", "2026-09-01T00:00:00+00:00", True),
        ("expired-window", "2026-08-29T00:00:00+00:00", "2026-08-30T00:00:00+00:00", False),
        ("future-window", "2026-09-02T00:00:00+00:00", "2026-09-03T00:00:00+00:00", False),
    )
    for name, start, end, should_allow in windows:
        raw = _copy_manifest(); raw.update(valid_from_utc=start, valid_until_utc=end)
        try:
            EngagementManifest.from_dict(raw).validate(now=now, enforce_window=True)
        except (EngagementError, TypeError, ValueError) as exc:
            allowed, detail = False, f"rejected: {exc}"
        else:
            allowed, detail = True, "accepted"
        out.append(_result("engagement-json", name, allowed == should_allow, detail))
    return out


# Policy/workflow mutation auditors -----------------------------------------
def audit_offense_text(text: str) -> list[str]:
    problems: list[str] = []
    for marker in (
        "owned-or-explicitly-authorized lab", "外部第三者の資産",
        "所有者または明示的なテスト権限", "campaign scope",
    ):
        if marker not in text:
            problems.append(f"missing authorization-boundary marker: {marker}")
    normalized = text.lower()
    for marker in (
        "any public host without authorization",
        "third-party assets require no authorization",
        "外部第三者の資産は認可不要",
    ):
        if marker.lower() in normalized:
            problems.append(f"unsafe authorization claim present: {marker}")
    return problems


def probe_offense_first_v2(root: Path) -> list[Finding]:
    path = root / "senju" / "OFFENSE_FIRST.md"
    if not path.is_file():
        return [_result("offense-first", "file-present", False, f"missing: {path}")]
    text = path.read_text(encoding="utf-8")
    problems = audit_offense_text(text)
    out = [_result("offense-first", "authorization-boundary-intact", not problems, "; ".join(problems) or "intact")]
    mutations = (
        ("remove-third-party-authorization", text.replace("所有者または明示的なテスト権限", "")),
        ("inject-unsafe-claim", text + "\nThird-party assets require no authorization.\n"),
    )
    for name, mutated in mutations:
        caught = bool(audit_offense_text(mutated))
        out.append(_result("offense-first", f"mutation-{name}", caught, "detected" if caught else "escaped"))
    return out


def audit_security_guard_text(text: str) -> list[str]:
    problems: list[str] = []
    for marker in (
        "permissions:\n  contents: read", "persist-credentials: false",
        "Block tracked secret files", "Block obvious credential material in tracked source",
        "Enforce fail-closed workflow policy", "Enforce external-evidence reality gate",
        "Block remote shell execution patterns", "Block direct interpolation of untrusted event text",
    ):
        if marker not in text:
            problems.append(f"missing workflow invariant: {marker}")
    for marker in ("pull_request_target:", "permissions: write-all", "persist-credentials: true", "continue-on-error: true"):
        if marker in text:
            problems.append(f"unsafe workflow marker present: {marker}")
    return problems


def probe_security_guard_v2(root: Path) -> list[Finding]:
    path = root / ".github" / "workflows" / "security-guard.yml"
    if not path.is_file():
        return [_result("security-guard-workflow", "file-present", False, f"missing: {path}")]
    text = path.read_text(encoding="utf-8")
    problems = audit_security_guard_text(text)
    out = [_result("security-guard-workflow", "live-contract", not problems, "; ".join(problems) or "intact")]
    mutations = (
        ("pull-request-target", text.replace("  pull_request:\n", "  pull_request_target:\n", 1)),
        ("write-permission", text.replace("  contents: read", "  contents: write", 1)),
        ("credential-persistence", text.replace("persist-credentials: false", "persist-credentials: true", 1)),
        ("continue-on-error", text + "\ncontinue-on-error: true\n"),
    )
    for name, mutated in mutations:
        caught = bool(audit_security_guard_text(mutated))
        out.append(_result("security-guard-workflow", f"mutation-{name}", caught, "detected" if caught else "escaped"))
    return out


# artifact_guard.py -----------------------------------------------------------
def _run_artifact_case(guard: Path, files: Mapping[str, str]) -> tuple[int, dict[str, Any], str]:
    with tempfile.TemporaryDirectory(prefix="senju-artifact-adversary-") as tmp:
        root = Path(tmp); dist = root / "dist"; dist.mkdir()
        for rel, content in files.items():
            target = dist / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
        report = root / "report.json"
        done = subprocess.run(
            [sys.executable, str(guard), str(dist), "--json", str(report)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        payload = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        return done.returncode, payload, (done.stdout + done.stderr).strip()


def probe_artifact_guard_v2(root: Path) -> list[Finding]:
    guard = root / "scripts" / "security" / "artifact_guard.py"
    if not guard.is_file():
        return [_result("artifact-guard", "file-present", False, f"missing: {guard}")]
    fake_key = "sk-" + "A" * 24
    cases: tuple[tuple[str, Mapping[str, str], bool, str | None], ...] = (
        ("clean", {"index.html": '<script src="https://example.com/app.js"></script>'}, True, None),
        ("source-map-file", {"assets/app.js.map": "{}"}, False, "artifact.source-map"),
        ("mixed-content", {"index.html": '<script src="http://example.com/app.js"></script>'}, False, "artifact.mixed-content"),
        ("localhost", {"assets/app.js": 'fetch("http://localhost:3000/api")'}, False, "artifact.localhost-reference"),
        ("source-map-reference", {"assets/app.js": "//# sourceMappingURL=app.js.map"}, False, "artifact.source-map-reference"),
        ("synthetic-secret", {"nested/config.JSON": f'{{"token":"{fake_key}"}}'}, False, "artifact.secret.openai-key"),
    )
    out: list[Finding] = []
    for name, files, should_pass, rule in cases:
        try:
            code, payload, output = _run_artifact_case(guard, files)
            rules = {str(x.get("rule")) for x in payload.get("findings", []) if isinstance(x, dict)}
            actual_pass = code == 0 and payload.get("status") == "pass"
            passed = actual_pass if should_pass else (code != 0 and payload.get("status") == "fail" and (rule in rules if rule else True))
            detail = f"exit={code}; status={payload.get('status')}; rules={sorted(rules)}"
            if output: detail += f"; output={output[:160]}"
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            passed, detail = False, f"runner error: {exc}"
        out.append(_result("artifact-guard", name, passed, detail))
    return out


# Active Autonomy Engine package --------------------------------------------
def _work(item_id: str, hypothesis: str, **kwargs: Any) -> WorkItem:
    return WorkItem(
        item_id=item_id,
        hypothesis=hypothesis,
        category=str(kwargs.pop("category", "resilience")),
        expected_value=float(kwargs.pop("expected_value", 0.5)),
        **kwargs,
    )


def probe_autonomy_v2(root: Path) -> list[Finding]:
    out: list[Finding] = []
    engine_path = root / "senju" / "senju" / "autonomy" / "engine.py"
    queue_path = root / "senju" / "senju" / "autonomy" / "queue.py"
    for name, path in (("engine-file-present", engine_path), ("queue-file-present", queue_path)):
        out.append(_result("autonomy-engine", name, path.is_file(), str(path)))
    if not engine_path.is_file() or not queue_path.is_file():
        return out

    engine_source = engine_path.read_text(encoding="utf-8")
    queue_source = queue_path.read_text(encoding="utf-8")
    for case, marker, source in (
        ("bounded-cycle-selector", "select_next(budget_matches=max_matches)", engine_source),
        ("simulation-tournament-boundary", "Tournament(cfg)", engine_source),
        ("persistent-queue", "self.save()", queue_source),
        ("dedup-key", "deduplication_key", queue_source),
        ("retry-bound", "max_retries", queue_source),
    ):
        out.append(_result("autonomy-engine", case, marker in source, "present" if marker in source else "missing"))

    with tempfile.TemporaryDirectory(prefix="senju-autonomy-v2-") as tmp:
        tmp_path = Path(tmp)
        queue = AutonomyQueue(tmp_path / "queue.json")
        first = _work("a", "same-hypothesis", cost_budget_matches=20)
        duplicate = _work("b", " SAME-HYPOTHESIS ", cost_budget_matches=20)
        first_ok, dup_ok = queue.enqueue(first), queue.enqueue(duplicate)
        out.append(_result("autonomy-engine", "hypothesis-dedup", first_ok and not dup_ok, f"first={first_ok}; duplicate={dup_ok}"))

        expensive = _work("expensive", "expensive", expected_value=0.99, cost_budget_matches=1000)
        cheap = _work("cheap", "cheap", expected_value=0.4, cost_budget_matches=30)
        queue.enqueue(expensive); queue.enqueue(cheap)
        selected = queue.select_next(budget_matches=50)
        out.append(_result("autonomy-engine", "budget-bound-selection", selected is not None and selected.cost_budget_matches <= 50, f"selected={getattr(selected, 'item_id', None)}"))

        retry_queue = AutonomyQueue(tmp_path / "retry.json")
        retry_item = _work("retry", "retry-boundary", max_retries=0, cost_budget_matches=20)
        retry_queue.enqueue(retry_item)
        picked = retry_queue.select_next(budget_matches=20)
        if picked:
            retry_queue.record_result(picked.item_id, success=False, blocker_reason="synthetic failure")
        blocked = retry_queue._items["retry"].status == WorkItemStatus.BLOCKED.value
        out.append(_result("autonomy-engine", "retry-exhaustion-blocks", blocked, retry_queue._items["retry"].status))

        # Invalid items may now fail at construction or enqueue. Both are correct fail-closed outcomes.
        invalid_specs: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
            ("unknown-authority-scope", "bad-scope", "bad scope", {"authority_scope": "arbitrary-admin"}),
            ("expected-value-over-one", "bad-ev", "bad expected value", {"expected_value": 1.5}),
            ("negative-cost-budget", "bad-cost", "bad cost", {"cost_budget_matches": -1}),
            ("negative-runtime-budget", "bad-runtime", "bad runtime", {"runtime_seconds_budget": -1.0}),
        )
        for name, item_id, hypothesis, kwargs in invalid_specs:
            validation_queue = AutonomyQueue(tmp_path / f"{name}.json")
            try:
                item = _work(item_id, hypothesis, **kwargs)
                accepted = validation_queue.enqueue(item)
                detail = "accepted by queue" if accepted else "rejected by queue"
            except (TypeError, ValueError) as exc:
                accepted = False
                detail = f"rejected at construction: {type(exc).__name__}: {exc}"
            out.append(_result("autonomy-engine", name, not accepted, detail))

        # Instantiation only: seeds queue/state locally, but never executes a tournament or network I/O.
        engine = AutonomyEngine(tmp_path / "engine-state")
        scopes = {x.authority_scope for x in engine.queue._items.values()}
        allowed_scopes = {"none", "threat_intel_public", "canary_telemetry"}
        out.append(_result("autonomy-engine", "seed-authority-scopes-bounded", scopes <= allowed_scopes, f"scopes={sorted(scopes)}"))
    return out


def run_v2(repo_root: Path | None = None, *, scope_cases: int = 4096, seed: int = 26002) -> AdversaryReport:
    root = repo_root or Path(__file__).resolve().parents[2]
    findings: list[Finding] = []
    findings.extend(probe_scopeguard_v2(count=scope_cases, seed=seed))
    findings.extend(probe_engagement_v2())
    findings.extend(probe_external_contact_v2())
    findings.extend(probe_offense_first_v2(root))
    findings.extend(probe_security_guard_v2(root))
    findings.extend(probe_artifact_guard_v2(root))
    findings.extend(probe_autonomy_v2(root))
    return AdversaryReport("senju-defense-adversary-suite/v2", seed, tuple(findings))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju Defense Adversary Suite V2")
    parser.add_argument("--json", dest="output", type=Path)
    parser.add_argument("--scope-cases", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=26002)
    parser.add_argument("--strict", action="store_true", help="return non-zero when any weakness is found")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_v2(scope_cases=max(0, args.scope_cases), seed=args.seed)
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps(report.to_dict()["summary"], ensure_ascii=False))
    else:
        print(rendered, end="")
    return 1 if args.strict and report.weaknesses else 0


if __name__ == "__main__":
    raise SystemExit(main())
