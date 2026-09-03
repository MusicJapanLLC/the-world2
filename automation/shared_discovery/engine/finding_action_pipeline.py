"""Finding -> Authority Review -> External Action pipeline.

Findings may nominate HTTPS targets and choose a read-only HTTP method. Authority
is still issued only by the independent reviewer for targets already covered by
explicit owner authorization. Execution remains credential-free and read-only.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .authority_reviewer import run_authority_review

ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = Path(__file__).resolve().parents[1] / "meta_state"
SAFE_METHODS = frozenset({"GET", "HEAD"})
DEFAULT_MAX_ACTIONS = 64
MAX_ACTIONS_HARD_LIMIT = 256


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _target_from_finding(item: dict[str, Any]) -> tuple[str, str] | None:
    raw = item.get("target_url", item.get("url"))
    if not isinstance(raw, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
        return None
    if not parsed.hostname:
        return None
    try:
        if parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    try:
        host = parsed.hostname.strip().rstrip(".").lower().encode("idna").decode("ascii")
    except (AttributeError, UnicodeError):
        return None
    if not host or any(ch in host for ch in "/?#@"):
        return None
    return raw, host


def _requested_method(item: dict[str, Any]) -> str | None:
    raw = item.get("method", item.get("action", "HEAD"))
    if not isinstance(raw, str):
        return None
    method = raw.strip().upper()
    return method if method in SAFE_METHODS else None


def _default_contact_factory(repo_root: Path) -> Callable[[str], Any]:
    senju_root = repo_root / "senju"
    if str(senju_root) not in sys.path:
        sys.path.insert(0, str(senju_root))
    external = importlib.import_module("senju.external")

    def build(host: str):
        policy = external.ExternalContactPolicy(
            allow_hosts=frozenset({host}),
            allow_http=False,
            allowed_methods=SAFE_METHODS,
            allow_delete=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=5.0,
            max_request_bytes=1024,
            max_response_bytes=64 * 1024,
            retries=1,
        )
        return external.ExternalContactClient(policy)

    return build


def run_finding_action_pipeline(
    state_dir: str | Path = STATE_DIR,
    *,
    repo_root: str | Path = ROOT,
    execute: bool = False,
    contact_factory: Callable[[str], Any] | None = None,
    max_actions: int = DEFAULT_MAX_ACTIONS,
) -> dict[str, Any]:
    """Plan or execute reviewed read-only actions on already-authorized roots."""
    state = Path(state_dir)
    root = Path(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    budget = max(1, min(int(max_actions), MAX_ACTIONS_HARD_LIMIT))

    source = _load_json(state / "adversary_findings.json", {})
    raw_findings = source.get("findings", []) if isinstance(source, dict) else []

    candidates: list[dict[str, Any]] = []
    rejected_findings: list[dict[str, Any]] = []
    for index, item in enumerate(raw_findings):
        if not isinstance(item, dict):
            rejected_findings.append({"index": index, "reason": "finding_not_object"})
            continue
        target = _target_from_finding(item)
        if target is None:
            rejected_findings.append({
                "index": index,
                "case": item.get("case"),
                "reason": "missing_or_invalid_https_target",
            })
            continue
        method = _requested_method(item)
        if method is None:
            rejected_findings.append({
                "index": index,
                "case": item.get("case"),
                "reason": "unsupported_read_method",
            })
            continue
        url, host = target
        candidates.append({
            "url": url,
            "host": host,
            "requested_method": method,
            "source": "adversary_finding",
            "case": item.get("case"),
            "layer": item.get("layer"),
            "severity": item.get("severity"),
            "decision": "candidate_only",
        })

    _write_json(
        state / "discovery_candidates.json",
        {
            "schema": "finding-derived-authority-candidates/v2",
            "generated_at": now,
            "source": "adversary_findings.json",
            "candidates": candidates,
        },
    )

    review = run_authority_review(state, repo_root=root)
    grants_doc = _load_json(state / "authority_reviewed_grants.json", {})
    grants = grants_doc.get("hosts", {}) if isinstance(grants_doc, dict) else {}

    planned: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    factory = contact_factory
    if execute and factory is None:
        factory = _default_contact_factory(root)

    for candidate in candidates:
        host = candidate["host"]
        url = candidate["url"]
        method = candidate["requested_method"]

        if len(planned) >= budget:
            blocked.append({"host": host, "url": url, "reason": "action_budget_exhausted"})
            continue

        grant = grants.get(host) if isinstance(grants, dict) else None
        if not isinstance(grant, dict):
            blocked.append({"host": host, "url": url, "reason": "no_reviewed_grant"})
            continue

        expires_at = int(grant.get("expires_at", 0))
        allowed_methods = set(grant.get("allowed_methods", []))
        if (
            expires_at <= now
            or not allowed_methods.issubset(SAFE_METHODS)
            or method not in allowed_methods
            or grant.get("credential_scope") != "none"
            or grant.get("effect") != "read_only"
            or grant.get("allow_http") is not False
            or grant.get("allow_delete") is not False
        ):
            blocked.append({"host": host, "url": url, "reason": "grant_not_read_only_safe"})
            continue

        action = {
            "host": host,
            "url": url,
            "method": method,
            "credential_scope": "none",
            "effect": "read_only",
            "authority_source": "independent_reviewed_existing_root",
            "grant_expires_at": expires_at,
        }
        planned.append(action)

        if not execute:
            continue
        try:
            client = factory(host)  # type: ignore[misc]
            receipt = client.contact(url, method=method)
            payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt)
            receipts.append(payload)
        except Exception as exc:
            errors.append({
                "host": host,
                "method": method,
                "error_type": type(exc).__name__,
                "reason": "external_contact_failed",
            })

    result = {
        "schema": "finding-authority-action-pipeline/v2",
        "generated_at": now,
        "mode": "execute_authorized_read_only" if execute else "plan_only",
        "finding_count": len(raw_findings),
        "candidate_count": len(candidates),
        "action_budget": budget,
        "review": review,
        "planned_actions": planned,
        "executed_count": len(receipts),
        "receipts": receipts,
        "blocked": blocked,
        "rejected_findings": rejected_findings,
        "errors": errors,
    }
    _write_json(state / "finding_action_result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--max-actions", type=int, default=DEFAULT_MAX_ACTIONS)
    parser.add_argument(
        "--execute-authorized-read-only",
        action="store_true",
        help="perform guarded GET/HEAD requests for independently reviewed existing roots",
    )
    args = parser.parse_args(argv)
    result = run_finding_action_pipeline(
        args.state_dir,
        repo_root=args.repo_root,
        execute=args.execute_authorized_read_only,
        max_actions=args.max_actions,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
