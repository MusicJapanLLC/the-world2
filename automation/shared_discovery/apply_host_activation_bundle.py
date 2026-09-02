#!/usr/bin/env python3
"""Apply or inspect host activation bundles.

Checks are advisory so candidate-heavy PRs are not blocked merely because Authorization,
allowlisting, or Senju profiling is still progressing. `--apply` remains strict because
that operation actually writes Authorization state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.host_activation_bundle import (
    HostActivationBundleError,
    apply_bundle,
    check_all_bundle_alignment,
    check_bundle_alignment,
    fetch_host_attestation,
    load_bundle,
    validate_attestation,
)


def _load_attestation(path: str | None) -> dict | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HostActivationBundleError("attestation file must contain a JSON object")
    return payload


def _advisory_error(exc: Exception, *, bundle: str | None = None) -> dict:
    return {
        "advisory": True,
        "blocking": False,
        "bundle": bundle,
        "ready": False,
        "reason": str(exc),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle")
    parser.add_argument("--attestation-file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-all", action="store_true")
    parser.add_argument("--verify-live", action="store_true")
    args = parser.parse_args()

    if sum(bool(x) for x in (args.apply, args.check, args.check_all)) != 1:
        parser.error("choose exactly one of --apply, --check, or --check-all")

    if args.check_all:
        try:
            result = check_all_bundle_alignment(args.repo_root)
            result["advisory"] = True
            result["blocking"] = False
        except Exception as exc:
            result = _advisory_error(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.bundle:
        parser.error("--bundle is required for --apply or --check")

    bundle_path = Path(args.bundle)
    if not bundle_path.is_absolute():
        bundle_path = Path(args.repo_root) / bundle_path

    if args.apply:
        # Applying Authorization is consequential; malformed or unverifiable evidence
        # still fails here even though CI inspection is advisory.
        bundle = load_bundle(bundle_path)
        supplied = _load_attestation(args.attestation_file)
        if supplied is not None:
            verified = validate_attestation(bundle, supplied)
        else:
            verified = fetch_host_attestation(bundle)
        result = apply_bundle(
            args.repo_root,
            bundle_path,
            attestation=verified,
            verify_live=False,
        )
        result["host_attestation_verified"] = True
        result["attestation_sha256"] = verified["sha256"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # --check is intentionally non-blocking. A candidate may be carried in a PR before
    # its Authorization or Senju profile is complete.
    try:
        bundle = load_bundle(bundle_path)
        verified = None
        if args.attestation_file:
            verified = validate_attestation(bundle, _load_attestation(args.attestation_file) or {})
        elif args.verify_live:
            try:
                verified = fetch_host_attestation(bundle)
            except Exception as exc:
                result = _advisory_error(exc, bundle=str(bundle_path))
                result["host_attestation_verified"] = False
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
        try:
            result = check_bundle_alignment(args.repo_root, bundle_path)
            result["ready"] = True
        except HostActivationBundleError as exc:
            result = _advisory_error(exc, bundle=str(bundle_path))
        result["advisory"] = True
        result["blocking"] = False
        result["host_attestation_verified"] = verified is not None
        if verified is not None:
            result["attestation_sha256"] = verified["sha256"]
    except Exception as exc:
        result = _advisory_error(exc, bundle=str(bundle_path))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
