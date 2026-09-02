"""Adversarial local fuzzer for ``senju.safety.ScopeGuard``.

This harness attacks ScopeGuard itself, not external systems. It performs no
network I/O and never resolves or connects to generated hostnames. The goal is
to find crashes, inconsistent decisions, and accidental fail-open behaviour at
the target_ref parsing boundary.
"""
from __future__ import annotations

import argparse
import json
import random
import string
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from senju.safety import ScopeGuard, ScopePolicy, ScopeViolation, default_lab_policy


EDGE_CASES = (
    "",
    " ",
    "\x00",
    "sim://",
    "sim://ok",
    "SIM://case-confusion",
    "labnet:dvwa",
    "labnet:",
    "127.0.0.1",
    "127.000.000.001",
    "0.0.0.0",
    "10.0.0.1",
    "169.254.1.1",
    "172.16.0.1",
    "192.168.0.1",
    "::1",
    "fe80::1",
    "8.8.8.8",
    "1.1.1.1",
    "example.com",
    "example.com.",
    " example.com",
    "example.com ",
    "https://example.com",
    "http://127.0.0.1",
    "user@example.com",
    "example.com/path",
    "example.com?x=1",
    "example.com#frag",
    "..",
    ".",
    "/",
    "\\",
    "localhost",
    "LOCALHOST",
    "xn--e1afmkfd.xn--p1ai",
    "例え.テスト",
    "💥" * 32,
    "a" * 4096,
)


@dataclass
class FuzzStats:
    cases: int = 0
    allowed: int = 0
    rejected: int = 0
    unexpected: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _random_ref(rng: random.Random) -> str:
    mode = rng.randrange(10)
    alphabet = string.ascii_letters + string.digits + ".:/?#@_-[]% "

    if mode == 0:
        return "sim://" + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 96)))
    if mode == 1:
        return "labnet:" + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 96)))
    if mode == 2:
        return ".".join(str(rng.randrange(0, 400)) for _ in range(4))
    if mode == 3:
        return ":".join(f"{rng.randrange(0, 65536):x}" for _ in range(rng.randrange(2, 9)))
    if mode == 4:
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 512)))
    if mode == 5:
        return "https://" + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 128)))
    if mode == 6:
        return "\x00" + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 64)))
    if mode == 7:
        return "例え" * rng.randrange(0, 64)
    if mode == 8:
        return "a" * rng.randrange(0, 16384)
    return rng.choice(EDGE_CASES)


def attack_once(guard: ScopeGuard, target_ref: str, stats: FuzzStats) -> None:
    """Hit ScopeGuard once and classify the result.

    ScopeViolation is an expected rejection. Any other exception is a fuzzer
    finding because arbitrary target_ref input must not crash the guard.
    """
    stats.cases += 1
    try:
        guard.check(target_ref)
    except ScopeViolation:
        stats.rejected += 1
    except Exception as exc:  # noqa: BLE001 - the fuzzer intentionally catches crashes
        stats.unexpected += 1
        raise AssertionError(
            f"ScopeGuard crashed for target_ref={target_ref!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    else:
        stats.allowed += 1


def assert_strict_invariants() -> None:
    """Check high-value fail-closed invariants before random fuzzing."""
    guard = ScopeGuard(default_lab_policy())

    for ref in (
        "8.8.8.8",
        "1.1.1.1",
        "example.com",
        "https://example.com",
        "http://example.com",
        "example.com.",
        " example.com",
        "SIM://not-the-sim-scheme",
    ):
        if guard.is_allowed(ref):
            raise AssertionError(f"strict policy unexpectedly allowed {ref!r}")

    for ref in ("sim://ok", "sim://", "sim://../../anything"):
        if not guard.is_allowed(ref):
            raise AssertionError(f"simulated reference unexpectedly rejected {ref!r}")

    allowlisted = ScopeGuard(ScopePolicy(allow_hosts={"owned.example"}))
    if not allowlisted.is_allowed("owned.example"):
        raise AssertionError("exact allowlisted host was rejected")
    if allowlisted.is_allowed("sub.owned.example"):
        raise AssertionError("allowlist unexpectedly widened to a subdomain")
    if allowlisted.is_allowed("owned.example.evil.invalid"):
        raise AssertionError("allowlist accepted a suffix-confusion hostname")


def run(iterations: int, seed: int, forever: bool = False) -> FuzzStats:
    rng = random.Random(seed)
    stats = FuzzStats()
    guard = ScopeGuard(default_lab_policy())

    assert_strict_invariants()

    for ref in EDGE_CASES:
        attack_once(guard, ref, stats)

    while forever or stats.cases < iterations:
        attack_once(guard, _random_ref(rng), stats)

    return stats


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continuously adversarial-test ScopeGuard locally")
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=0x5C0FE)
    parser.add_argument("--json-out")
    parser.add_argument(
        "--forever",
        action="store_true",
        help="run until interrupted; still performs no network I/O",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")

    stats = run(args.iterations, args.seed, args.forever)
    evidence = {
        "schema": "scopeguard-fuzz-evidence/v1",
        "seed": int(args.seed),
        "requested_iterations": int(args.iterations),
        "network_io": False,
        "payloads_retained": False,
        "stats": stats.to_dict(),
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "SCOPEGUARD_FUZZ_OK "
        f"cases={stats.cases} allowed={stats.allowed} "
        f"rejected={stats.rejected} unexpected={stats.unexpected}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
