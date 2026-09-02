"""Integrity checks for the real multi-guard adversary target stack.

This module never contacts external systems. It verifies that the adversary harness is
bound to the exact repository guard sources recorded in ``adversary_provenance.json``
and then runs metamorphic, pairwise contract mutations against the real policy files.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path

from .multiguard_adversary_v2 import (
    OFFENSE_FIRST_PATH,
    SECURITY_GUARD_PATH,
    validate_offense_first_document,
    validate_security_guard_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_PATH = REPO_ROOT / "senju" / "adversary_provenance.json"


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    payload = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def verify_guard_provenance() -> tuple[str, ...]:
    if not PROVENANCE_PATH.is_file():
        return (f"missing provenance manifest: {PROVENANCE_PATH}",)

    try:
        payload = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"invalid provenance manifest: {exc}",)

    if payload.get("schema") != "senju-adversary-provenance/v1":
        return ("unexpected provenance schema",)

    sources = payload.get("guard_sources")
    if not isinstance(sources, dict) or not sources:
        return ("provenance guard_sources must be a non-empty object",)

    errors: list[str] = []
    for raw_path, expected_blob in sorted(sources.items()):
        if not isinstance(raw_path, str) or not isinstance(expected_blob, str):
            errors.append("provenance entries must be string path -> string blob sha")
            continue
        candidate = (REPO_ROOT / raw_path).resolve()
        try:
            candidate.relative_to(REPO_ROOT.resolve())
        except ValueError:
            errors.append(f"provenance path escapes repository: {raw_path}")
            continue
        if not candidate.is_file():
            errors.append(f"missing pinned guard source: {raw_path}")
            continue
        actual = _git_blob_sha(candidate)
        if actual != expected_blob:
            errors.append(
                f"guard source drift: {raw_path} expected={expected_blob} actual={actual}"
            )
    return tuple(errors)


_OFFENSE_FORBIDDEN = {
    "UNAUTHORIZED_EXTERNAL_EXECUTION=ALLOW": "forbidden:unrestricted-external",
    "THIRD_PARTY_AUTHORIZATION=IMPLICIT": "forbidden:implicit-third-party",
    "SCOPEGUARD=DISABLED": "forbidden:disable-scopeguard",
    "ALLOW_ANY_HOST=true": "forbidden:allow-any-host",
    "SECRETS_SCOPE=UNRESTRICTED": "forbidden:unbounded-secrets",
    "ENGAGEMENT_REQUIRED=false": "forbidden:skip-engagement",
    "AUTONOMY_BOUNDARY=NONE": "forbidden:unbounded-autonomy",
}

_SECURITY_FORBIDDEN = {
    "permissions: write-all": "forbidden:write-all",
    "persist-credentials: true": "forbidden:checkout-credentials",
    "pull_request_target:": "forbidden:pull-request-target",
    "contents: write": "forbidden:contents-write",
    "actions: write": "forbidden:actions-write",
    "id-token: write": "forbidden:id-token-write",
    "packages: write": "forbidden:packages-write",
    "issues: write": "forbidden:issues-write",
    "pull-requests: write": "forbidden:pull-requests-write",
    "checks: write": "forbidden:checks-write",
    "deployments: write": "forbidden:deployments-write",
    "statuses: write": "forbidden:statuses-write",
    "security-events: write": "forbidden:security-events-write",
    "attestations: write": "forbidden:attestations-write",
}


def _pairwise_contract_errors(
    baseline: str,
    forbidden: dict[str, str],
    validator,
    label: str,
) -> list[str]:
    failures: list[str] = []

    baseline_errors = tuple(validator(baseline))
    if baseline_errors:
        failures.append(f"{label} baseline invalid: {baseline_errors}")
        return failures

    items = tuple(forbidden.items())
    for marker, expected_error in items:
        observed = set(validator(baseline + f"\n{marker}\n"))
        if expected_error not in observed:
            failures.append(f"{label} single mutation escaped: {marker}")

    for (marker_a, error_a), (marker_b, error_b) in combinations(items, 2):
        mutated = baseline + f"\n{marker_a}\n{marker_b}\n"
        observed = set(validator(mutated))
        missing = {error_a, error_b} - observed
        if missing:
            failures.append(
                f"{label} pair mutation escaped: {marker_a!r} + {marker_b!r}; missing={sorted(missing)}"
            )
    return failures


def verify_metamorphic_contracts() -> tuple[str, ...]:
    errors: list[str] = []
    errors.extend(
        _pairwise_contract_errors(
            OFFENSE_FIRST_PATH.read_text(encoding="utf-8"),
            _OFFENSE_FORBIDDEN,
            validate_offense_first_document,
            "offense-first",
        )
    )
    errors.extend(
        _pairwise_contract_errors(
            SECURITY_GUARD_PATH.read_text(encoding="utf-8"),
            _SECURITY_FORBIDDEN,
            validate_security_guard_workflow,
            "security-guard",
        )
    )
    return tuple(errors)


def assert_adversary_integrity() -> None:
    errors = (*verify_guard_provenance(), *verify_metamorphic_contracts())
    if errors:
        rendered = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"multi-guard adversary integrity failed:\n{rendered}")
