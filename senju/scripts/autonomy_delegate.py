#!/usr/bin/env python3
"""Route Senju advisor recommendations into approval-free internal delegation.

This router expands Senju's autonomy inside the repository without turning discovered
third-party targets into write authority. It consumes only structured advisor output,
chooses a deterministic route, and emits a bounded delegation packet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SAFE_REPO_PREFIXES = (
    "senju/",
    "value-lab/",
    "company-society/",
    "automation/world/",
    "automation/control_plane/",
    "automation/ai_foundry/",
    "automation/agent_factory/",
    "automation/codegen/",
    "api/",
    "public/",
    "scripts/",
    "docs/",
    "README",
    "PORTFOLIO",
)

SENSITIVE_MARKERS = (
    ".github/workflows/security",
    "automation/security/",
    "scripts/security/",
    "senju/senju/safety.py",
    "outside-world/",
    "scopeguard",
    "credential",
    "secret",
    "private key",
    "token extraction",
    "disable guard",
    "bypass guard",
    "remove guard",
    "unrestricted external write",
    "third-party write",
    "external exploit",
    "intrusion",
)

PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: Any, limit: int) -> str:
    text = CONTROL_RE.sub("", str(value or "")).strip()
    return text[:limit]


def _paths(text: str) -> list[str]:
    out: list[str] = []
    for match in PATH_RE.findall(text):
        value = match.strip("`'\".,:;()[]{}")
        if value and value not in out:
            out.append(value)
    return out[:32]


def _is_sensitive(text: str, paths: list[str]) -> bool:
    haystack = (text + "\n" + "\n".join(paths)).lower()
    return any(marker in haystack for marker in SENSITIVE_MARKERS)


def _all_senju(paths: list[str]) -> bool:
    return bool(paths) and all(path.startswith("senju/") for path in paths)


def _safe_repo_paths(paths: list[str]) -> bool:
    if not paths:
        return True
    return all(any(path.startswith(prefix) for prefix in SAFE_REPO_PREFIXES) for path in paths)


def route(advisor: dict[str, Any]) -> dict[str, Any]:
    decision = advisor.get("decision") if isinstance(advisor.get("decision"), dict) else {}
    implement = bool(decision.get("implement"))
    request = _clean(decision.get("request"), 12000)
    rationale = _clean(decision.get("rationale"), 4000)
    priority = _clean(decision.get("priority"), 32).lower() or "medium"
    if priority not in {"low", "medium", "high"}:
        priority = "medium"

    if not implement or not request:
        return {
            "schema": "senju-autonomy-delegation/v1",
            "route": "none",
            "reason": "advisor did not select an implementation candidate",
            "priority": priority,
            "delegation_key": "",
            "title": "",
            "body": "",
            "paths": [],
        }

    paths = _paths(request)
    combined = request + "\n" + rationale
    if _is_sensitive(combined, paths):
        route_name = "hold"
        reason = "recommendation touches authority/security-sensitive surfaces"
    elif _all_senju(paths):
        route_name = "self"
        reason = "recommendation is contained in Senju's existing implementation lane"
    elif not _safe_repo_paths(paths):
        route_name = "hold"
        reason = "recommendation names repository paths outside the autonomous delegation set"
    else:
        route_name = "jules"
        reason = "cross-repository improvement can be delegated through the existing Jules PR lane"

    digest_input = json.dumps(
        {"request": request, "paths": paths, "route": route_name},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    key = hashlib.sha256(digest_input).hexdigest()[:20]

    first_line = next((line.strip() for line in request.splitlines() if line.strip()), "Senju improvement")
    first_line = re.sub(r"\s+", " ", first_line)[:120]
    title = f"[Jules][Senju] {first_line}" if route_name == "jules" else ""
    body = ""
    if route_name == "jules":
        body = (
            "Senju selected this improvement autonomously from its advisor/evolution loop.\n\n"
            f"senju-delegation-key: {key}\n"
            f"priority: {priority}\n"
            f"detected_paths: {', '.join(paths) if paths else '(not explicitly named)'}\n\n"
            "## Requested improvement\n"
            + request
            + "\n\n## Advisor rationale\n"
            + rationale
            + "\n\n## Execution contract\n"
            "Implement the smallest focused change that satisfies the request, run relevant tests, "
            "and open a pull request. Inspect current repository state and active overlap first. "
            "Do not expand credentials, external target authority, or third-party write/exploit scope. "
            "Do not push directly to the default branch. The resulting PR will enter the existing "
            "OpenHands independent audit lane.\n"
        )[:30000]

    return {
        "schema": "senju-autonomy-delegation/v1",
        "route": route_name,
        "reason": reason,
        "priority": priority,
        "delegation_key": key,
        "title": title,
        "body": body,
        "paths": paths,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--advisor", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    advisor = json.loads(Path(args.advisor).read_text(encoding="utf-8"))
    result = route(advisor)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("route", "priority", "delegation_key")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
