"""Senju PR #252 self-development publisher.

The generator is deliberately narrow: it can materialize content-addressed local
lab manifests under ``senju/labs`` and, outside ``--dry-run``, publish only those
files through a Senju-provenance pull request.  It cannot modify workflow,
credential, network-authority, or external-target configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "senju-self-code-gen/v2"
DEFAULT_BASE = "claude/employee-onboarding-setup-udm86"
SUBPROCESS_TIMEOUT = 45


def _run(args: list[str], *, timeout: int = SUBPROCESS_TIMEOUT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _manifest_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest is not an object: {path}")
    if payload.get("schema") != "senju-auto-lab/v3":
        raise ValueError(f"unexpected manifest schema: {path}")
    fingerprint = str(payload.get("fingerprint") or "")
    if len(fingerprint) != 64:
        raise ValueError(f"invalid manifest fingerprint: {path}")
    if payload.get("host") is not None:
        raise ValueError(f"local lab manifest unexpectedly names a host: {path}")
    return payload


def campaign_fingerprint(paths: list[Path]) -> str:
    parts: list[dict[str, str]] = []
    for path in sorted(paths, key=lambda p: str(p)):
        payload = _manifest_payload(path)
        parts.append({"path": str(path), "fingerprint": str(payload["fingerprint"])})
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _existing_equivalent_pr(fingerprint: str) -> str | None:
    marker = f"[senju-plan:{fingerprint}]"
    result = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "url,body,headRefName,title",
        ]
    )
    rows = json.loads(result.stdout or "[]")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if marker in str(row.get("body") or ""):
            return str(row.get("url") or "") or None
    return None


def _publish_pr(paths: list[Path], fingerprint: str, base: str) -> tuple[str | None, str | None]:
    existing = _existing_equivalent_pr(fingerprint)
    if existing:
        return existing, None

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    branch = f"senju/auto-lab-{fingerprint[:12]}-{run_id}-{attempt}"
    _run(["git", "checkout", "-b", branch])

    safe_paths: list[str] = []
    for path in paths:
        value = path.as_posix()
        if not value.startswith("senju/labs/"):
            raise ValueError(f"self-development publication escaped senju/labs: {value}")
        safe_paths.append(value)

    _run(["git", "add", "--", *safe_paths])
    diff = _run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        return None, branch
    if diff.returncode not in {0, 1}:
        raise RuntimeError(diff.stderr.strip() or "git diff failed")

    _run(["git", "commit", "-m", f"senju(auto-lab): coverage plan {fingerprint[:12]}"])
    _run(["git", "push", "origin", f"HEAD:{branch}"], timeout=90)

    body = (
        "Generated autonomously by the Senju PR #252 self-development loop.\n\n"
        f"[senju-plan:{fingerprint}]\n"
        f"Generated local lab manifests: {len(paths)}\n"
        "Authority: local synthetic/owned-lab manifests only. No external target, secret, "
        "workflow permission, or network scope is added.\n\n"
        "This PR may enter the existing Senju provenance auto-review/merge lane."
    )
    created = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            f"feat(senju): auto-lab plan {fingerprint[:12]}",
            "--body",
            body,
        ],
        timeout=90,
    )
    return created.stdout.strip() or None, branch


def _write_report(path: str | None, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="senju/state/last-evolution-summary.json")
    parser.add_argument("--labs-dir", default="senju/labs")
    parser.add_argument("--max-manifests", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-json")
    parser.add_argument("--base", default=os.environ.get("BASE_BRANCH", DEFAULT_BASE))
    args = parser.parse_args()

    from pathlib import Path as _Path
    import sys

    sys.path.insert(0, str(_Path(__file__).parent.parent))
    from senju.lab_planner import plan

    generated = plan(args.summary, args.labs_dir, args.max_manifests)
    fingerprint = campaign_fingerprint(generated) if generated else ""
    pr_url: str | None = None
    branch: str | None = None
    deduplicated = False

    if generated and not args.dry_run:
        existing = _existing_equivalent_pr(fingerprint)
        if existing:
            pr_url = existing
            deduplicated = True
        else:
            pr_url, branch = _publish_pr(generated, fingerprint, args.base)

    report = {
        "schema": REPORT_SCHEMA,
        "mode": "candidate-only" if args.dry_run else "autonomous-pr",
        "dry_run": bool(args.dry_run),
        "generated_count": len(generated),
        "generated": [str(path) for path in generated],
        "campaign_fingerprint": fingerprint,
        "deduplicated": deduplicated,
        "pr": pr_url,
        "branch": branch,
        "authority": "senju/labs-only",
    }
    _write_report(args.report_json, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
