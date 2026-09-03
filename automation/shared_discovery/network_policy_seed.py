#!/usr/bin/env python3
"""Build production network-policy evidence from already explicit authority.

This does not create authority. It ensures that every production expansion cycle
actively exercises the roots/exact hosts that are already authorized, so the runtime
policy cannot remain empty merely because an unrelated external frontier did not
mention an owned host in that cycle.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from engine.network_policy_expansion import (
    _load_envelope,
    _reviewed_exact_hosts,
    _standing_exact_hosts,
)


def build_seed(state_dir: Path, repo_root: Path) -> dict[str, Any]:
    now = int(time.time())
    envelope = _load_envelope(state_dir)
    roots = set(envelope["roots"])
    exact = _standing_exact_hosts(repo_root) | _reviewed_exact_hosts(state_dir, now)
    hosts = sorted(roots | exact)
    return {
        "schema": "meta-network-policy-explicit-seed/v1",
        "generated_at": now,
        "source": "already_explicit_network_authority",
        "hosts": hosts,
        "urls": [f"https://{host}/" for host in hosts],
        "finding": "explicit_authority_should_be_active_in_runtime_policy",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="automation/codegen/meta_state")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = build_seed(Path(args.state_dir), Path(args.repo_root))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"seed_hosts": len(doc["hosts"]), "hosts": doc["hosts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
