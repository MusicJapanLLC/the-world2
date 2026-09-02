"""Unified PROJECT SENJU SPEAR entrypoint.

SPEAR now supports two execution authority models:

1. trusted-owner mode: persistent Owner/BOSS scope, no engagement_id, exact-host
   manifest, or validity window required for each run;
2. legacy engagement mode: the existing bounded EngagementManifest workflow.

The trusted-owner mode is intended for assets already covered by a persistent
owned/explicitly-authorized domain scope.
"""
from __future__ import annotations

import argparse
from typing import Iterable

from .authorized_assessment import EngagementManifest, AuthorizedAssessmentRunner, dry_run_report, _write_json
from .trusted_scope import TrustedOwnerScope, TrustedScopeRunner, _load_requests


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PROJECT SENJU SPEAR")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--trusted-scope", help="persistent Owner/BOSS trusted scope JSON")
    mode.add_argument("--engagement", help="legacy per-engagement manifest JSON")
    parser.add_argument("--requests", help="Red-selected request plan for trusted-owner mode")
    parser.add_argument("--execute", action="store_true", help="execute legacy engagement mode")
    parser.add_argument("--out", help="write sanitized report JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.trusted_scope:
        if not args.requests:
            parser.error("--requests is required with --trusted-scope")
        scope = TrustedOwnerScope.load(args.trusted_scope)
        report = TrustedScopeRunner(scope).run(_load_requests(args.requests))
        _write_json(report, args.out)
        return 0

    manifest = EngagementManifest.load(args.engagement)
    report = AuthorizedAssessmentRunner(manifest).run() if args.execute else dry_run_report(manifest)
    _write_json(report, args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
