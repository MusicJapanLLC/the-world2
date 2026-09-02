"""Adversarial regression against Senju's real repository guard surfaces.

No guarded component is copied or reimplemented here. The harness resolves the
actual source files/classes, records their SHA-256 provenance, and invokes their
real validation paths. External network effects are replaced only at the final
transport seam, after the real ExternalContactClient checks have run.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping

from .authorized_assessment import EngagementError, EngagementManifest, build_plan
from .autonomy.engine import AutonomyEngine
from .autonomy.queue import AutonomyQueue, WorkItem
from .external import ExternalContactClient, ExternalContactError, ExternalContactPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = dt.datetime(2026, 8, 31, 0, 0, tzinfo=dt.timezone.utc)

TARGETS: dict[str, Path] = {
    "offense-first": REPO_ROOT / "senju" / "OFFENSE_FIRST.md",
    "engagement-json": REPO_ROOT / "senju" / "senju" / "authorized_assessment.py",
    "external-contact": REPO_ROOT / "senju" / "senju" / "external.py",
    "security-guard": REPO_ROOT / ".github" / "workflows" / "security-guard.yml",
    "artifact-guard": REPO_ROOT / "scripts" / "security" / "artifact_guard.py",
    "autonomy-engine": REPO_ROOT / "senju" / "senju" / "autonomy" / "engine.py",
}


@dataclass(frozen=True)
class Probe:
    target: str
    name: str
    passed: bool
    detail: str


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _same_source(obj: object, expected: Path) -> None:
    source = inspect.getsourcefile(obj)
    if source is None or Path(source).resolve() != expected.resolve():
        raise AssertionError(f"source mismatch: {source!r} != {_relative(expected)}")


def _provenance() -> dict[str, dict[str, str]]:
    for path in TARGETS.values():
        if not path.is_file():
            raise AssertionError(f"real target missing: {_relative(path)}")
    _same_source(EngagementManifest, TARGETS["engagement-json"])
    _same_source(ExternalContactClient, TARGETS["external-contact"])
    _same_source(AutonomyEngine, TARGETS["autonomy-engine"])
    return {
        name: {"path": _relative(path), "sha256": _sha(path)}
        for name, path in TARGETS.items()
    }


def _probe(target: str, name: str, fn: Callable[[], str]) -> Probe:
    try:
        return Probe(target, name, True, fn())
    except Exception as exc:  # deliberate: failures must become machine-readable evidence
        return Probe(target, name, False, f"{type(exc).__name__}: {exc}")


def _must_reject(exc_type: type[BaseException], fn: Callable[[], object]) -> str:
    try:
        fn()
    except exc_type as exc:
        return f"rejected:{type(exc).__name__}:{exc}"
    except Exception as exc:
        raise AssertionError(
            f"expected {exc_type.__name__}, got {type(exc).__name__}: {exc}"
        ) from exc
    raise AssertionError(f"expected {exc_type.__name__}, operation was accepted")


def _offense_probes() -> list[Probe]:
    def contract() -> str:
        path = TARGETS["offense-first"]
        text = path.read_text(encoding="utf-8")
        required = (
            "Arena / synthetic / owned-or-explicitly-authorized lab",
            "所有者または明示的なテスト権限",
            "外部資産に対する認可境界",
        )
        forbidden = (
            "UNAUTHORIZED_EXTERNAL_EXECUTION=ALLOW",
            "THIRD_PARTY_AUTHORIZATION=IMPLICIT",
            "SCOPEGUARD=DISABLED",
            "ALLOW_ANY_HOST=true",
            "ENGAGEMENT_REQUIRED=false",
        )
        missing = [x for x in required if x not in text]
        bad = [x for x in forbidden if x in text]
        if missing or bad:
            raise AssertionError(f"missing={missing}; forbidden={bad}")
        return f"real-file:{_relative(path)}:{_sha(path)[:16]}"

    return [_probe("offense-first", "real-policy-contract", contract)]


def _manifest() -> dict[str, object]:
    return {
        "engagement_id": "real-surface-regression",
        "owner": "MusicJapanLLC",
        "authorization_reference": "owned-lab-regression",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": ["reachability", "root_snapshot"],
        "max_requests_per_target": 2,
        "max_rps": 1.0,
        "allow_http": False,
        "destructive": False,
    }


def _engagement_probes() -> list[Probe]:
    out: list[Probe] = []

    def valid() -> str:
        manifest = EngagementManifest.from_dict(_manifest())
        plan = build_plan(manifest)
        if not plan or any(row.target_host != "example.com" for row in plan):
            raise AssertionError("planner escaped exact target")
        return f"real-manifest-plan:requests={len(plan)}"

    out.append(_probe("engagement-json", "accept-bounded-owned-target", valid))

    cases: list[tuple[str, Callable[[dict[str, object]], None]]] = [
        ("reject-missing-authorization", lambda raw: raw.__setitem__("authorization_reference", "")),
        ("reject-destructive", lambda raw: raw.__setitem__("destructive", True)),
        ("reject-request-budget-bypass", lambda raw: raw.__setitem__("max_requests_per_target", 99)),
        ("reject-rate-bypass", lambda raw: raw.__setitem__("max_rps", 2.01)),
        ("reject-wildcard-host", lambda raw: raw.__setitem__("targets", [{"host": "*.example.com"}])),
        ("reject-duplicate-target", lambda raw: raw.__setitem__("targets", [{"host": "example.com"}, {"host": "example.com"}])),
        ("reject-unknown-check", lambda raw: raw.__setitem__("allowed_checks", ["reachability", "active_exploit"])),
        ("reject-empty-check-set", lambda raw: raw.__setitem__("allowed_checks", [])),
        ("reject-http-target-without-opt-in", lambda raw: raw.__setitem__("targets", [{"host": "example.com", "scheme": "http"}])),
        ("reject-half-validity-window", lambda raw: raw.__setitem__("valid_from_utc", "2026-08-30T00:00:00Z")),
    ]
    for name, mutate in cases:
        def run(mutate: Callable[[dict[str, object]], None] = mutate) -> str:
            raw = copy.deepcopy(_manifest())
            mutate(raw)
            return _must_reject(EngagementError, lambda: EngagementManifest.from_dict(raw))
        out.append(_probe("engagement-json", name, run))

    def reversed_window() -> str:
        raw = _manifest()
        raw["valid_from_utc"] = "2026-08-31T02:00:00Z"
        raw["valid_until_utc"] = "2026-08-31T01:00:00Z"
        return _must_reject(EngagementError, lambda: EngagementManifest.from_dict(raw))

    out.append(_probe("engagement-json", "reject-reversed-window", reversed_window))

    def expired() -> str:
        raw = _manifest()
        raw["valid_from_utc"] = "2026-01-01T00:00:00Z"
        raw["valid_until_utc"] = "2026-01-02T00:00:00Z"
        manifest = EngagementManifest.from_dict(raw)
        return _must_reject(
            EngagementError,
            lambda: manifest.validate(now=FIXED_NOW, enforce_window=True),
        )

    out.append(_probe("engagement-json", "reject-expired-window", expired))
    return out


class _Response:
    status = 204
    headers: dict[str, str] = {}

    def read(self, limit: int = -1) -> bytes:
        del limit
        return b""

    def close(self) -> None:
        return None


class _Opener:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: object, *, timeout: float) -> _Response:
        del request, timeout
        self.calls += 1
        return _Response()


def _public_resolver(host: str, port: int) -> tuple[str, ...]:
    del host, port
    return ("93.184.216.34",)


def _client(
    resolver: Callable[[str, int], tuple[str, ...]] = _public_resolver,
) -> tuple[ExternalContactClient, _Opener]:
    opener = _Opener()
    policy = ExternalContactPolicy.from_hosts(
        ["example.com"],
        allow_http=False,
        allow_delete=False,
        follow_redirects=False,
        retries=0,
    )
    client = ExternalContactClient(
        policy,
        resolver=resolver,
        opener=opener,
        sleeper=lambda _: None,
    )
    return client, opener


def _external_probes() -> list[Probe]:
    out: list[Probe] = []

    def allowed() -> str:
        client, opener = _client()
        receipt = client.contact("https://example.com/health", method="GET")
        if receipt.status != 204 or opener.calls != 1:
            raise AssertionError(f"status={receipt.status}; transport_calls={opener.calls}")
        return "real-client-validation-and-transport-seam-ok"

    out.append(_probe("external-contact", "accept-exact-allowlisted-public-host", allowed))

    def rejection(
        name: str,
        url: str,
        *,
        method: str = "GET",
        resolver=None,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Probe:
        def run() -> str:
            client, opener = _client(resolver or _public_resolver)
            detail = _must_reject(
                ExternalContactError,
                lambda: client.contact(url, method=method, body=body, headers=headers),
            )
            if opener.calls != 0:
                raise AssertionError("rejected request reached transport")
            return detail
        return _probe("external-contact", name, run)

    out.append(rejection("reject-non-allowlisted-host-before-io", "https://attacker.invalid/"))
    out.append(rejection("reject-private-resolution-before-io", "https://example.com/", resolver=lambda _h, _p: ("127.0.0.1",)))
    out.append(rejection("reject-mixed-public-private-dns-before-io", "https://example.com/", resolver=lambda _h, _p: ("93.184.216.34", "127.0.0.1")))
    out.append(rejection("reject-empty-dns-before-io", "https://example.com/", resolver=lambda _h, _p: ()))
    out.append(rejection("reject-invalid-dns-answer-before-io", "https://example.com/", resolver=lambda _h, _p: ("not-an-ip",)))
    out.append(rejection("reject-url-credentials", "https://user:pass@example.com/"))
    out.append(rejection("reject-plain-http", "http://example.com/"))
    out.append(rejection("reject-unsupported-scheme", "ftp://example.com/"))
    out.append(rejection("reject-invalid-port", "https://example.com:99999/"))
    out.append(rejection("reject-delete-without-opt-in", "https://example.com/object/1", method="DELETE"))
    out.append(rejection("reject-unsupported-method", "https://example.com/", method="TRACE"))
    out.append(rejection("reject-get-body", "https://example.com/", method="GET", body=b"fault"))
    out.append(rejection("reject-oversized-request-body", "https://example.com/", method="POST", body=b"X" * (64 * 1024 + 1)))
    out.append(rejection("reject-host-header-override", "https://example.com/", headers={"Host": "attacker.invalid"}))
    out.append(rejection("reject-header-name-injection", "https://example.com/", headers={"X-Test\r\nInjected": "1"}))
    out.append(rejection("reject-header-value-injection", "https://example.com/", headers={"X-Test": "ok\r\nInjected: 1"}))
    return out


def _workflow_probes() -> list[Probe]:
    def contract() -> str:
        path = TARGETS["security-guard"]
        text = path.read_text(encoding="utf-8")
        required = (
            "contents: read",
            "persist-credentials: false",
            "Block tracked secret files",
            "Scan newly introduced lines for secrets",
            "Run real-surface adversary regression",
            "python -m senju.real_surface_adversary",
            "python automation/security/workflow_policy_entrypoint.py",
            "python automation/security/reality_gate.py",
        )
        forbidden = (
            "pull_request_target:",
            "permissions: write-all",
            "persist-credentials: true",
            "contents: write",
            "id-token: write",
        )
        missing = [x for x in required if x not in text]
        bad = [x for x in forbidden if x in text]
        if missing or bad:
            raise AssertionError(f"missing={missing}; forbidden={bad}")
        return f"real-workflow:{_sha(path)[:16]}"

    return [_probe("security-guard", "real-workflow-self-contract", contract)]


def _run_artifact_guard(files: Mapping[str, str]) -> tuple[int, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="real-artifact-adversary-") as tmp:
        root = Path(tmp)
        dist = root / "dist"
        dist.mkdir()
        for relative, text in files.items():
            path = dist / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        report = root / "report.json"
        proc = subprocess.run(
            [sys.executable, str(TARGETS["artifact-guard"]), str(dist), "--json", str(report)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        return proc.returncode, payload


def _artifact_probes() -> list[Probe]:
    out: list[Probe] = []

    def clean() -> str:
        rc, data = _run_artifact_guard({"index.html": "<html><body>ok</body></html>"})
        if rc != 0 or data.get("status") != "pass":
            raise AssertionError(f"rc={rc}; status={data.get('status')}")
        return "real-artifact-guard-clean-pass"

    out.append(_probe("artifact-guard", "clean-artifact", clean))

    def blocked(name: str, files: Mapping[str, str], expected_rule: str) -> Probe:
        def run() -> str:
            rc, data = _run_artifact_guard(files)
            rules = {
                item.get("rule")
                for item in data.get("findings", [])
                if isinstance(item, dict)
            }
            if rc != 1 or expected_rule not in rules:
                raise AssertionError(f"rc={rc}; rules={sorted(str(x) for x in rules)}")
            return f"real-artifact-guard-blocked:{expected_rule}"
        return _probe("artifact-guard", name, run)

    synthetic = "sk-" + ("A" * 28)
    out.append(blocked("block-secret-like-output", {"app.js": f"const x='{synthetic}';"}, "artifact.secret.openai-key"))
    out.append(blocked("block-localhost-output", {"app.js": "fetch('http://127.0.0.1:3000/admin')"}, "artifact.localhost-reference"))
    out.append(blocked("block-source-map", {"bundle.js.map": "{}"}, "artifact.source-map"))
    return out


def _autonomy_probes() -> list[Probe]:
    out: list[Probe] = []

    def bounded_queue() -> str:
        _same_source(AutonomyEngine, TARGETS["autonomy-engine"])
        with tempfile.TemporaryDirectory(prefix="real-autonomy-adversary-") as tmp:
            engine = AutonomyEngine(tmp)
            if len(engine.queue._items) < 3:
                raise AssertionError("real engine failed to seed bounded queue")
            if engine.queue.select_next(budget_matches=1) is not None:
                raise AssertionError("real queue selected work above budget")
            if (Path(tmp) / "autonomy_reports").exists():
                raise AssertionError("tournament executed during rejection probe")
        return "real-engine-source-and-budget-boundary-ok"

    out.append(_probe("autonomy-engine", "bounded-real-engine-queue", bounded_queue))

    def invalid_category() -> str:
        return _must_reject(
            ValueError,
            lambda: WorkItem(
                item_id="adv-category",
                hypothesis="synthetic invalid category",
                category="unbounded_external_action",
                expected_value=0.5,
            ),
        )

    out.append(_probe("autonomy-engine", "reject-unknown-category", invalid_category))

    def invalid_authority_scope() -> str:
        return _must_reject(
            ValueError,
            lambda: WorkItem(
                item_id="adv-authority",
                hypothesis="synthetic invalid authority scope",
                category="security",
                expected_value=0.5,
                authority_scope="all_external_hosts",
            ),
        )

    out.append(_probe("autonomy-engine", "reject-unknown-authority-scope", invalid_authority_scope))

    def excessive_budget() -> str:
        return _must_reject(
            ValueError,
            lambda: WorkItem(
                item_id="adv-budget",
                hypothesis="synthetic excessive budget",
                category="test",
                expected_value=0.5,
                cost_budget_matches=5001,
            ),
        )

    out.append(_probe("autonomy-engine", "reject-excessive-budget", excessive_budget))

    def invalid_selector_budget() -> str:
        with tempfile.TemporaryDirectory(prefix="real-autonomy-selector-") as tmp:
            queue = AutonomyQueue(Path(tmp) / "queue.json")
            return _must_reject(ValueError, lambda: queue.select_next(budget_matches=5001))

    out.append(_probe("autonomy-engine", "reject-selector-budget-bypass", invalid_selector_budget))

    def corrupt_state() -> str:
        with tempfile.TemporaryDirectory(prefix="real-autonomy-corrupt-") as tmp:
            path = Path(tmp) / "queue.json"
            path.write_text('{"items":[{"item_id":"poisoned"', encoding="utf-8")
            queue = AutonomyQueue(path)
            if queue._items:
                raise AssertionError("corrupt persisted queue was trusted")
        return "corrupt-state-failed-closed"

    out.append(_probe("autonomy-engine", "ignore-corrupt-persisted-state", corrupt_state))

    def dedup_queue() -> str:
        with tempfile.TemporaryDirectory(prefix="real-autonomy-dedup-") as tmp:
            queue = AutonomyQueue(Path(tmp) / "queue.json")
            first = WorkItem(
                item_id="adv-dedup-1",
                hypothesis="same bounded pressure hypothesis",
                category="security",
                expected_value=0.8,
                cost_budget_matches=10,
                parameters={"matches": 10},
            )
            second = WorkItem(
                item_id="adv-dedup-2",
                hypothesis="same bounded pressure hypothesis",
                category="security",
                expected_value=0.9,
                cost_budget_matches=10,
                parameters={"matches": 10},
            )
            if not queue.enqueue(first):
                raise AssertionError("first work item was unexpectedly rejected")
            if queue.enqueue(second):
                raise AssertionError("duplicate pressure work item bypassed deduplication")
        return "real-queue-deduplication-held"

    out.append(_probe("autonomy-engine", "deduplicate-pressure-work", dedup_queue))
    return out


def run() -> dict[str, object]:
    provenance = _provenance()
    results: list[Probe] = []
    results.extend(_offense_probes())
    results.extend(_engagement_probes())
    results.extend(_external_probes())
    results.extend(_workflow_probes())
    results.extend(_artifact_probes())
    results.extend(_autonomy_probes())
    failed = [item for item in results if not item.passed]
    return {
        "schema": "senju-real-surface-adversary/v1",
        "mode": "real-repository-surfaces",
        "passed": not failed,
        "total": len(results),
        "failed_count": len(failed),
        "provenance": provenance,
        "results": [asdict(item) for item in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="output", type=Path)
    args = parser.parse_args(argv)
    report = run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())