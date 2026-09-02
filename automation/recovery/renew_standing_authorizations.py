#!/usr/bin/env python3
"""Operational entrypoint for META/X standing-authorization recovery renewal.

Recovery workers, replicas, checkpoint recovery, and cache recovery can invoke this
script directly against the live Senju state directory.  Recovery metadata can trigger
renewal but cannot replace the current standing-authorization registry.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENJU_PACKAGE_ROOT = ROOT / "senju"
if str(SENJU_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(SENJU_PACKAGE_ROOT))

from senju.meta.renewal_recovery import (  # noqa: E402
    RECOVERY_RENEWAL_SOURCES,
    renew_all_active_from_recovery_signal,
    renew_from_recovery_signal,
)

DEFAULT_REGISTRY = ROOT / "senju" / "state" / "standing_authorizations.json"
DEFAULT_LEASE_LOG = ROOT / "senju" / "state" / "standing_authorization_leases.ndjson"


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True, choices=["META", "X"])
    parser.add_argument("--source", required=True, choices=sorted(RECOVERY_RENEWAL_SOURCES))
    parser.add_argument("--authorization-reference")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--lease-log", type=Path, default=DEFAULT_LEASE_LOG)
    parser.add_argument("--lease-seconds", type=int, default=6 * 60 * 60)
    parser.add_argument("--reason", default="still_needed")
    args = parser.parse_args()

    if args.authorization_reference:
        result = renew_from_recovery_signal(
            source=args.source,
            actor=args.actor,
            authorization_reference=args.authorization_reference,
            registry_path=args.registry,
            lease_log_path=args.lease_log,
            lease_seconds=args.lease_seconds,
            reason=args.reason,
        )
    else:
        result = renew_all_active_from_recovery_signal(
            source=args.source,
            actor=args.actor,
            registry_path=args.registry,
            lease_log_path=args.lease_log,
            lease_seconds=args.lease_seconds,
            reason=args.reason,
        )

    print(json.dumps(_jsonable(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
