"""Coordinated adversarial pressure tests for Senju defense layers.

The team attacks *copies, parsers, contracts, and synthetic inputs* only. It does
not disable guards, expand authorization, perform external network I/O, or
modify production policy. The goal is to discover surprising accepts/rejects
and missing defensive invariants before real code reaches production.
"""
from __future__ import annotations

import argparse
import ast
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .authorized_assessment import EngagementError, EngagementManifest
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
class TeamReport:
    schema: str
    findings: tuple[Finding, ...]

    @property
    def weaknesses(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if not item.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "summary": {
                "checks": len(self.findings),
                "passed": sum(1 for item in self.findings if item.passed),
                "weaknesses": len(self.weaknesses),
            },
            "findings": [asdict(item) for item in self.findings],
        }


def _scope_fuzz_cases(count: int = 1000, seed: int = 260) -> tuple[ProbeCase, ...]:
    """Generate deterministic malformed/external refs expected to stay blocked."""
    rng = random.Random(seed)
    bases = (
        "example.com",
        "EXAMPLE.COM",
        "https://example.com",
        "http://example.com",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "::1",
        "labnet:fixture",
        "SIM://fixture",
        "sim:/fixture",
        "sim%3A//fixture",
    )
    wrappers: tuple[Callable[[str], str], ...] = (
        lambda value: value,
        lambda value: " " + value,
        lambda value: value + " ",
        lambda value: "\t" + value,
        lambda value: value + ":443",
        lambda value: "//" + value,
        lambda value: value + "/path",
        lambda value: value + "#fragment",
    )
    generated: list[ProbeCase] = []
    for index in range(count):
        value = rng.choice(wrappers)(rng.choice(bases))
        generated.append(ProbeCase(f"fuzz-{index:04d}", value, False))
    return tuple(generated)


def probe_scopeguard() -> list[Finding]:
    guard = ScopeGuard(default_lab_policy())
    cases = DEFAULT_CASES + _scope_fuzz_cases()
    findings: list[Finding] = []
    for result in probe_guard(guard, cases):
        findings.append(
            Finding(
                layer="scopeguard",
                case=result.case.name,
                passed=not result.surprising,
                detail=result.detail,
            )
        )
    return findings


def probe_external_contact() -> list[Finding]:
    policy = ExternalContactPolicy.from_hosts(["example.com"], allow_http=False)
    cases = (
        ("exact-https", "https://example.com/", True),
        ("http-disabled", "http://example.com/", False),
        ("subdomain-not-exact", "https://api.example.com/", False),
        ("suffix-lookalike", "https://example.com.invalid/", False),
        ("userinfo", "https://user@example.com/", False),
        ("password", "https://user:pass@example.com/", False),
        ("non-http-scheme", "ftp://example.com/", False),
        ("missing-host", "https:///path", False),
    )
    findings: list[Finding] = []
    for name, url, should_allow in cases:
        try:
            _parse_url(url, policy)
        except ExternalContactError as exc:
            allowed = False
            detail = str(exc)
        else:
            allowed = True
            detail = "accepted"
        findings.append(Finding("external-contact", name, allowed == should_allow, detail))
    return findings


def _valid_manifest() -> dict[str, object]:
    return {
        "engagement_id": "synthetic-adversary",
        "owner": "synthetic-owner",
        "authorization_reference": "synthetic://local-test-only",
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
    baseline = _valid_manifest()
    cases.append(("valid-baseline", baseline, True))

    wildcard = _valid_manifest()
    wildcard["targets"] = [{"host": "*.example.com"}]
    cases.append(("wildcard-host", wildcard, False))

    no_authority = _valid_manifest()
    no_authority["authorization_reference"] = ""
    cases.append(("missing-authorization-reference", no_authority, False))

    destructive = _valid_manifest()
    destructive["destructive"] = True
    cases.append(("destructive-flag", destructive, False))

    duplicate = _valid_manifest()
    duplicate["targets"] = [{"host": "example.com"}, {"host": "example.com"}]
    cases.append(("duplicate-hosts", duplicate, False))

    bad_window = _valid_manifest()
    bad_window["valid_until_utc"] = "2026-08-30T00:00:00+00:00"
    cases.append(("reversed-window", bad_window, False))

    too_fast = _valid_manifest()
    too_fast["max_rps"] = 50.0
    cases.append(("excessive-rps", too_fast, False))

    findings: list[Finding] = []
    for name, raw, should_allow in cases:
        try:
            EngagementManifest.from_dict(raw)
        except (EngagementError, TypeError, ValueError) as exc:
            allowed = False
            detail = str(exc)
        else:
            allowed = True
            detail = "accepted"
        findings.append(Finding("engagement", name, allowed == should_allow, detail))
    return findings


def _contract_findings(layer: str, path: Path, markers: tuple[str, ...]) -> list[Finding]:
    if not path.is_file():
        return [Finding(layer, "file-present", False, f"missing: {path}")]
    text = path.read_text(encoding="utf-8")
    return [
        Finding(layer, marker, marker in text, "present" if marker in text else "missing")
        for marker in markers
    ]


def probe_execution_boundary(repo_root: Path) -> list[Finding]:
    return _contract_findings(
        "execution-boundary",
        repo_root / "senju" / "OFFENSE_FIRST.md",
        (
            "owned-or-explicitly-authorized lab",
            "外部第三者の資産",
            "明示的なテスト権限",
        ),
    )


def probe_security_guard(repo_root: Path) -> list[Finding]:
    return _contract_findings(
        "security-guard-workflow",
        repo_root / ".github" / "workflows" / "security-guard.yml",
        (
            "persist-credentials: false",
            "permissions:\n  contents: read",
            "Block tracked secret files",
            "Block obvious credential material in tracked source",
            "Block remote shell execution patterns",
            "Block direct interpolation of untrusted event text",
            "workflow_policy_entrypoint.py",
            "reality_gate.py",
        ),
    )


def probe_artifact_guard(repo_root: Path) -> list[Finding]:
    findings = _contract_findings(
        "artifact-guard",
        repo_root / "scripts" / "security" / "artifact_guard.py",
        (
            "artifact.source-map",
            "artifact.localhost-reference",
            "artifact.source-map-reference",
            "artifact.secret.",
            "artifact.mixed-content",
        ),
    )
    findings.extend(
        _contract_findings(
            "artifact-guard",
            repo_root / ".github" / "workflows" / "standment-security-gate.yml",
            ("python scripts/security/artifact_guard.py baton/dist",),
        )
    )
    return findings


def probe_autonomy_isolation(repo_root: Path) -> list[Finding]:
    path = repo_root / "senju" / "senju" / "autonomy" / "engine.py"
    if not path.is_file():
        return [Finding("autonomy-isolation", "file-present", False, f"missing: {path}")]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = ("urllib", "requests", "httpx", "socket", "senju.external", "external")
    findings = [
        Finding(
            "autonomy-isolation",
            f"no-import:{name}",
            not any(item == name or item.startswith(name + ".") for item in imports),
            f"imports={sorted(imports)}",
        )
        for name in forbidden
    ]
    source = path.read_text(encoding="utf-8")
    findings.append(Finding("autonomy-isolation", "uses-tournament", "Tournament(" in source, "simulation core"))
    return findings


def run_team(repo_root: Path | None = None) -> TeamReport:
    root = repo_root or Path(__file__).resolve().parents[2]
    findings: list[Finding] = []
    findings.extend(probe_scopeguard())
    findings.extend(probe_external_contact())
    findings.extend(probe_engagement())
    findings.extend(probe_execution_boundary(root))
    findings.extend(probe_security_guard(root))
    findings.extend(probe_artifact_guard(root))
    findings.extend(probe_autonomy_isolation(root))
    return TeamReport("senju-defense-adversary-team/v1", tuple(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Senju's coordinated defensive adversary team")
    parser.add_argument("--json", dest="output", type=Path)
    args = parser.parse_args()
    report = run_team()
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if report.weaknesses else 0


if __name__ == "__main__":
    raise SystemExit(main())
