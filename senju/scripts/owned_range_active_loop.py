#!/usr/bin/env python3
"""CLI for Senju's evolving active loop on an explicitly owned web range."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from senju.owned_range_active import OwnedRangeActiveRunner
from senju.trusted_scope import TrustedOwnerScope


def _load(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Run evolving active tests inside a trusted owned range")
    ap.add_argument("--scope", default="senju/config/authorized-test-range.json")
    ap.add_argument("--base-url", default="https://kabeya-authorized-test-range.onrender.com/")
    ap.add_argument("--memory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--memory-out", required=True)
    ap.add_argument("--max-pages", type=int, default=18)
    ap.add_argument("--max-probes", type=int, default=24)
    ap.add_argument("--max-writes", type=int, default=3)
    ap.add_argument("--write-cooldown-seconds", type=int, default=3600)
    ap.add_argument("--seed", type=int, default=20260831)
    args = ap.parse_args()

    scope = TrustedOwnerScope.load(args.scope)
    runner = OwnedRangeActiveRunner(scope, base_url=args.base_url)
    report, memory = runner.run(
        memory_data=_load(args.memory),
        max_pages=max(1, min(args.max_pages, 30)),
        max_probe_requests=max(2, min(args.max_probes, 60)),
        max_writes=max(0, min(args.max_writes, 5)),
        write_cooldown_seconds=max(0, min(args.write_cooldown_seconds, 86400)),
        seed=args.seed,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    memory_out = Path(args.memory_out)
    memory_out.parent.mkdir(parents=True, exist_ok=True)
    memory_out.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "SENJU_OWNED_RANGE_ACTIVE_VERIFIED "
        f"host={report['authorized_host']} requests={report['request_count']} "
        f"writes={report['write_attempts']} counterexamples={report['counterexample_count']} "
        f"digest={report['digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
