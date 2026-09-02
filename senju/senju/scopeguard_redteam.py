"""ScopeGuard-only adversarial stress harness.

This module attacks the *decision surface* of :class:`senju.safety.ScopeGuard` only.
It never opens sockets, performs HTTP requests, spawns shell commands, or contacts
external systems. Its only target is ScopeGuard's string-to-decision behavior.

Use ``--iterations 0`` for an intentionally unbounded local run that continues
until interrupted. CI should use a finite iteration count.
"""
from __future__ import annotations

import argparse
import json
import random
import string
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .safety import ScopeGuard, ScopeViolation, default_lab_policy


SEED_CORPUS = (
    "",
    " ",
    "\t",
    "\n",
    "sim://ok",
    "sim://",
    "SIM://case-change",
    " sim://leading-space",
    "sim:/missing-slash",
    "sim:///extra-slash",
    "labnet:dvwa",
    "labnet:",
    "LABNET:dvwa",
    "127.0.0.1",
    "::1",
    "10.0.0.1",
    "169.254.169.254",
    "0.0.0.0",
    "8.8.8.8",
    "203.0.113.10",
    "2130706433",
    "0x7f000001",
    "example.com",
    "example.com.",
    "EXAMPLE.COM",
    "localhost",
    "localhost.",
    "https://example.com",
    "http://127.0.0.1",
    "user@example.com",
    "example.com/path",
    "example.com?x=1",
    "example.com#frag",
    "evil.example\nsecond-line",
    "sim://ok\x00tail",
    "ｓｉｍ://fullwidth",
    "sim：//unicode-colon",
    "research-target:anything",
)

_ALPHABET = string.ascii_letters + string.digits + ".:/?#@_-[]%\\\x00\t\n "


@dataclass(frozen=True)
class Finding:
    kind: str
    target_ref: str
    detail: str


@dataclass
class RunReport:
    schema: str = "senju-scopeguard-redteam/v1"
    seed: int = 0
    iterations_requested: int = 0
    iterations_completed: int = 0
    accepted: int = 0
    rejected: int = 0
    crashes: int = 0
    decision_mismatches: int = 0
    suspicious_accepts: int = 0
    elapsed_seconds: float = 0.0
    findings: list[Finding] | None = None

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw["findings"] = [asdict(item) for item in (self.findings or [])]
        return raw


def _mutate(rng: random.Random, value: str) -> str:
    """Produce one aggressive string mutation without touching the network."""
    ops = rng.randint(1, 4)
    out = value
    for _ in range(ops):
        choice = rng.randrange(9)
        if choice == 0:
            pos = rng.randrange(len(out) + 1)
            out = out[:pos] + rng.choice(_ALPHABET) + out[pos:]
        elif choice == 1 and out:
            pos = rng.randrange(len(out))
            out = out[:pos] + out[pos + 1 :]
        elif choice == 2 and out:
            pos = rng.randrange(len(out))
            out = out[:pos] + rng.choice(_ALPHABET) + out[pos + 1 :]
        elif choice == 3:
            out = rng.choice((" ", "\t", "\n", "\x00")) + out
        elif choice == 4:
            out = out + rng.choice((" ", ".", "/", "?x=1", "#frag", "\x00tail"))
        elif choice == 5:
            out = out.swapcase()
        elif choice == 6:
            out = out.replace(":", rng.choice((":", "：", "%3a")), 1)
        elif choice == 7:
            out = rng.choice(SEED_CORPUS) + out
        else:
            size = rng.randint(0, 96)
            out = "".join(rng.choice(_ALPHABET) for _ in range(size))
    return out[:512]


def _suspicious_strict_accept(target_ref: str) -> bool:
    """Strict default policy should accept only the explicit sim:// namespace."""
    return bool(target_ref) and not target_ref.startswith("sim://")


def _exercise_one(guard: ScopeGuard, target_ref: str) -> tuple[bool, list[Finding]]:
    findings: list[Finding] = []

    try:
        predicted = guard.is_allowed(target_ref)
    except Exception as exc:  # pragma: no cover - finding path
        return False, [Finding("is_allowed_crash", target_ref, repr(exc))]

    try:
        guard.check(target_ref)
        accepted = True
    except ScopeViolation:
        accepted = False
    except Exception as exc:  # pragma: no cover - finding path
        return False, [Finding("check_crash", target_ref, repr(exc))]

    if predicted != accepted:
        findings.append(
            Finding(
                "decision_mismatch",
                target_ref,
                f"is_allowed={predicted} check_accepted={accepted}",
            )
        )

    if accepted and _suspicious_strict_accept(target_ref):
        findings.append(
            Finding(
                "suspicious_strict_accept",
                target_ref,
                "default_lab_policy accepted a non-sim target_ref",
            )
        )

    return accepted, findings


def run_scopeguard_redteam(
    *,
    iterations: int,
    seed: int | None = None,
    max_findings: int = 200,
) -> RunReport:
    """Hammer ScopeGuard with adversarial target_ref values.

    ``iterations == 0`` means run until interrupted. No network I/O is performed.
    """
    if iterations < 0:
        raise ValueError("iterations must be >= 0")
    if max_findings < 1:
        raise ValueError("max_findings must be >= 1")

    actual_seed = int(time.time_ns() & 0xFFFFFFFF) if seed is None else int(seed)
    rng = random.Random(actual_seed)
    report = RunReport(seed=actual_seed, iterations_requested=iterations, findings=[])
    started = time.monotonic()
    guard = ScopeGuard(default_lab_policy())

    index = 0
    try:
        while iterations == 0 or index < iterations:
            base = SEED_CORPUS[index % len(SEED_CORPUS)] if index < len(SEED_CORPUS) else rng.choice(SEED_CORPUS)
            candidate = base if index < len(SEED_CORPUS) else _mutate(rng, base)

            accepted, findings = _exercise_one(guard, candidate)
            report.accepted += int(accepted)
            report.rejected += int(not accepted)

            for finding in findings:
                if finding.kind.endswith("crash"):
                    report.crashes += 1
                elif finding.kind == "decision_mismatch":
                    report.decision_mismatches += 1
                elif finding.kind == "suspicious_strict_accept":
                    report.suspicious_accepts += 1
                if len(report.findings or []) < max_findings:
                    assert report.findings is not None
                    report.findings.append(finding)

            index += 1
            report.iterations_completed = index
    except KeyboardInterrupt:
        pass
    finally:
        report.elapsed_seconds = round(time.monotonic() - started, 6)

    return report


def _write_report(report: RunReport, path: str | Path | None) -> None:
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(rendered, end="")
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adversarially stress ScopeGuard only")
    parser.add_argument(
        "--iterations",
        type=int,
        default=100_000,
        help="number of cases; 0 means unbounded until interrupted",
    )
    parser.add_argument("--seed", type=int, help="deterministic RNG seed")
    parser.add_argument("--max-findings", type=int, default=200)
    parser.add_argument("--out", help="write JSON report to this path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_scopeguard_redteam(
        iterations=args.iterations,
        seed=args.seed,
        max_findings=args.max_findings,
    )
    _write_report(report, args.out)

    # Fail CI only for crashes, internal decision disagreement, or strict fail-open.
    return int(bool(report.crashes or report.decision_mismatches or report.suspicious_accepts))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
