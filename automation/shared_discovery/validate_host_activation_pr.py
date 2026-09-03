#!/usr/bin/env python3
"""Report new-host activation completeness without blocking candidate-heavy PRs.

The previous version rejected partial host PRs. That made candidate intake too rigid.
This validator is intentionally advisory: it reports how far each host has progressed
through candidate -> Authorization -> allowed target -> Senju profile, but does not turn
an incomplete host into a CI failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from engine.host_activation_bundle import HostActivationBundleError, check_bundle_alignment, load_bundle

TARGETS_PATH = "AUTHORIZED_TEST_TARGETS.json"
POLICY_PATH = "automation/codegen/meta_state/discovery_policy.json"
BUNDLE_PREFIX = "automation/codegen/authority_bundles/"


class PRContractError(RuntimeError):
    """Reserved for malformed local git state, not incomplete host progression."""


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise PRContractError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _json_at(ref: str, path: str) -> dict[str, Any]:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return {}
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _explicit_targets(doc: Mapping[str, Any]) -> set[str]:
    rows = doc.get("targets", [])
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("host") or "").strip().lower().rstrip(".")
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("owner_authorization") or "").strip().lower() == "explicit"
        and str(row.get("host") or "").strip()
    }


def _explicit_profiles(doc: Mapping[str, Any]) -> set[str]:
    profiles = doc.get("action_profiles", {})
    if not isinstance(profiles, Mapping):
        return set()
    return {
        str(host).strip().lower().rstrip(".")
        for host, profile in profiles.items()
        if isinstance(profile, Mapping)
        and str(profile.get("owner_authorization") or "").strip().lower() == "explicit"
    }


def _changed_bundle_paths(base: str, head: str, repo_root: Path) -> list[Path]:
    names = _git("diff", "--name-only", base, head, "--", BUNDLE_PREFIX).splitlines()
    out: list[Path] = []
    for name in names:
        name = name.strip()
        if not name.endswith(".json") or name.endswith(".example.json"):
            continue
        path = repo_root / name
        if path.is_file():
            out.append(path)
    return out


def _senju_status(bundle: Mapping[str, Any]) -> dict[str, Any]:
    raw = bundle.get("senju_experimentation")
    if not isinstance(raw, Mapping):
        return {"enabled": False, "ready": False, "methods": [], "paths": []}
    methods = [str(x).strip().upper() for x in raw.get("allowed_methods", []) if str(x).strip()]
    paths = [str(x).strip() for x in raw.get("trial_paths", []) if str(x).strip()]
    return {
        "enabled": bool(raw.get("enabled", False)),
        "ready": bool(raw.get("enabled", False) and methods and paths),
        "methods": methods,
        "paths": paths,
        "allow_path_learning": bool(raw.get("allow_path_learning", False)),
        "allow_method_switch": bool(raw.get("allow_method_switch", False)),
        "payload_variants_per_route": int(raw.get("payload_variants_per_route", 1) or 1),
    }


def validate_pr(base: str, head: str, *, repo_root: str | Path = ".") -> dict[str, Any]:
    root = Path(repo_root)
    base_targets = _explicit_targets(_json_at(base, TARGETS_PATH))
    head_targets = _explicit_targets(_json_at(head, TARGETS_PATH))
    base_profiles = _explicit_profiles(_json_at(base, POLICY_PATH))
    head_profiles = _explicit_profiles(_json_at(head, POLICY_PATH))
    new_targets = sorted(head_targets - base_targets)
    new_profiles = sorted(head_profiles - base_profiles)

    bundle_paths = _changed_bundle_paths(base, head, root)
    bundles: dict[str, Path] = {}
    bundle_status: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for path in bundle_paths:
        try:
            bundle = load_bundle(path)
        except Exception as exc:  # advisory by design
            warnings.append(f"bundle_unreadable:{path}:{exc}")
            continue
        host = str(bundle["host"])
        bundles[host] = path
        aligned = False
        alignment_error = None
        try:
            check_bundle_alignment(root, path)
            aligned = True
        except HostActivationBundleError as exc:
            alignment_error = str(exc)
        bundle_status[host] = {
            "aligned": aligned,
            "alignment_error": alignment_error,
            "senju": _senju_status(bundle),
        }

    all_hosts = sorted(set(new_targets) | set(new_profiles) | set(bundles))
    progression: dict[str, dict[str, Any]] = {}
    for host in all_hosts:
        authorized = host in head_targets
        profiled = host in head_profiles
        bundled = host in bundles
        senju = bundle_status.get(host, {}).get("senju", {"ready": False})
        if authorized and profiled and bool(senju.get("ready")):
            stage = "senju_trial_ready"
        elif authorized and profiled:
            stage = "authorized_profiled"
        elif authorized:
            stage = "authorized_target_only"
        elif bundled:
            stage = "candidate_bundle"
        else:
            stage = "candidate"
        progression[host] = {
            "stage": stage,
            "canonical_authorization": authorized,
            "exact_profile": profiled,
            "activation_bundle": bundled,
            "senju_trial_ready": bool(senju.get("ready", False)),
        }

    return {
        "schema": "the-world-host-activation-pr-advisory/v1",
        "base": base,
        "head": head,
        "new_explicit_targets": new_targets,
        "new_explicit_profiles": new_profiles,
        "changed_active_bundles": sorted(bundles),
        "progression": progression,
        "warnings": warnings,
        "blocking": False,
        "partial_new_host_pr_allowed": True,
        "candidate_only_pr_allowed": True,
        "authorization_only_pr_allowed": True,
        "profile_can_follow_later": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json-out")
    args = parser.parse_args()
    result = validate_pr(args.base, args.head, repo_root=args.repo_root)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        destination = Path(args.json_out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
