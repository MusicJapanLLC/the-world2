#!/usr/bin/env python3
"""Select at most two automatic deployment permits per UTC hour.

Two permits/hour means at most 48 automatic deploys/day across the targets routed
through this controller, leaving two deployments of headroom under the requested
50/day ceiling.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _tracked(paths: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(item.decode() for item in proc.stdout.split(b"\0") if item)


def fingerprint(paths: list[str]) -> str:
    digest = hashlib.sha256()
    files = _tracked(paths)
    if not files:
        raise RuntimeError(f"deployment source path set contains no tracked files: {paths}")
    for rel in files:
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update((ROOT / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def permit_fingerprint(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        return ""
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return str(raw.get("fingerprint") or "")


def select(config: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    max_per_hour = int(config.get("max_per_hour", 2))
    if not 1 <= max_per_hour <= 2:
        raise ValueError("max_per_hour must stay between 1 and 2")
    targets = list(config.get("targets") or [])
    pending: list[dict[str, str]] = []
    for target in targets:
        fp = fingerprint(list(target["source_paths"]))
        permit = str(target["permit_path"])
        if fp != permit_fingerprint(permit):
            pending.append({
                "name": str(target["name"]),
                "permit_path": permit,
                "fingerprint": fp,
            })
    stamp = now or dt.datetime.now(dt.timezone.utc)
    pending.sort(key=lambda item: item["name"])
    if pending:
        offset = int(stamp.timestamp() // 3600) % len(pending)
        pending = pending[offset:] + pending[:offset]
    chosen = pending[:max_per_hour]
    return {
        "schema": "the-world-deploy-budget/v1",
        "generated_at_utc": stamp.isoformat(timespec="seconds"),
        "max_per_hour": max_per_hour,
        "max_automatic_per_day": max_per_hour * 24,
        "pending_count": len(pending),
        "selected": chosen,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="automation/deploy-budget.json")
    parser.add_argument("--out")
    args = parser.parse_args()
    config = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    result = select(config)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
