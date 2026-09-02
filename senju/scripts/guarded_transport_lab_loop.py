#!/usr/bin/env python3
"""Run Senju's guarded multi-route transport experiment loop.

The runner only contacts targets with a live grant in
`automation/codegen/meta_state/authority_reviewed_grants.json`.
It never expands authority, bypasses ExternalContactClient, or follows an unreviewed
redirect destination.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "senju"))

from senju.transport_lab import (  # noqa: E402
    load_reviewed_authority,
    run_transport_loop,
)

STATE_DIR = REPO_ROOT / "automation" / "codegen" / "meta_state"
GRANTS_FILE = STATE_DIR / "authority_reviewed_grants.json"
CANDIDATES_FILE = STATE_DIR / "discovery_candidates.json"
OUTPUT_FILE = REPO_ROOT / "senju" / "state" / "guarded_transport_lab.json"


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_targets(authority, explicit_url: str | None = None) -> list[str]:
    if explicit_url:
        return [explicit_url]

    doc = _load_json(CANDIDATES_FILE)
    urls: list[str] = []
    seen: set[str] = set()
    for item in doc.get("candidates", []):
        if not isinstance(item, dict):
            continue
        raw = item.get("url")
        if not isinstance(raw, str) or raw in seen:
            continue
        try:
            parsed = urllib.parse.urlsplit(raw)
            host = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
        except (ValueError, UnicodeError):
            continue
        if parsed.scheme.lower() != "https" or not authority.allows(host):
            continue
        seen.add(raw)
        urls.append(raw)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded guarded Senju transport experiments")
    parser.add_argument("--url", help="single target URL; must already have a live reviewed grant")
    parser.add_argument("--cycles", type=int, default=3, help="loop cycles, hard-bounded to 1..10")
    parser.add_argument("--rounds", type=int, default=3, help="strategy rounds per target, hard-bounded to 1..10")
    parser.add_argument("--max-targets", type=int, default=5, help="targets per cycle, hard-bounded to 1..10")
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="delay between cycles, bounded to 1..3600")
    args = parser.parse_args()

    cycles = max(1, min(int(args.cycles), 10))
    rounds = max(1, min(int(args.rounds), 10))
    max_targets = max(1, min(int(args.max_targets), 10))
    sleep_seconds = max(1.0, min(float(args.sleep_seconds), 3600.0))

    authority = load_reviewed_authority(GRANTS_FILE)
    if not authority.hosts:
        print("[transport-lab] no live reviewed authority grants; nothing to do")
        return 0

    all_cycles: list[dict] = []
    for cycle_no in range(1, cycles + 1):
        # Reload before each cycle so reviewer grant expiry/revocation takes effect.
        authority = load_reviewed_authority(GRANTS_FILE)
        targets = _candidate_targets(authority, args.url)[:max_targets]
        if not targets:
            print("[transport-lab] no currently reviewed candidate targets")
            break

        cycle_results: list[dict] = []
        print(f"[transport-lab] cycle={cycle_no}/{cycles} targets={len(targets)} rounds={rounds}")
        for target in targets:
            try:
                result = run_transport_loop(target, authority, rounds=rounds)
                cycle_results.append(result)
                print(
                    f"[transport-lab] target={result['target_host']} "
                    f"winner={result['winner']} events={len(result['events'])}"
                )
            except Exception as exc:  # fail one target, not the full bounded batch
                cycle_results.append({
                    "schema": "senju-guarded-transport-lab/error-v1",
                    "target_url": target,
                    "error": str(exc)[:300],
                    "guard_bypass": False,
                })
                print(f"[transport-lab] target failed: {target}: {exc}")

        all_cycles.append({"cycle": cycle_no, "results": cycle_results})
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps(
                {
                    "schema": "senju-guarded-transport-lab-loop/v1",
                    "generated_at": int(time.time()),
                    "cycles": all_cycles,
                    "guard_bypass": False,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        if cycle_no < cycles:
            time.sleep(sleep_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
