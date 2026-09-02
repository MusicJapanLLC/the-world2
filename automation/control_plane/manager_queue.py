#!/usr/bin/env python3
"""OIDC-backed bridge from TOMOKI Manager to the canonical Supabase P100 queue.

This bridge deliberately performs only the MANAGER stage. It may claim a bounded
number of `TOMOKI / MANAGER` tasks and move them to `review` with a structured
triage package. It never marks its own review as verified/done, and it never
applies security, permission, credential, billing, external-write, or other
irreversible mutations.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AUDIENCE = "the-world-worker"
EDGE_URL = "https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/tomoki-manager-gateway"
OUTPUT_PATH = Path("reports/control-plane/manager-queue-cycle.json")
OIDC_HOST_SUFFIX = ".actions.githubusercontent.com"


def _validated_oidc_url(raw_url: str) -> str:
    """Return a GitHub-hosted HTTPS OIDC endpoint with our audience appended.

    GitHub injects ACTIONS_ID_TOKEN_REQUEST_URL into the hosted runner.  Treat
    that environment value as untrusted anyway: require the documented GitHub
    Actions host family, HTTPS, no credentials, and no non-standard port before
    any network request is made.
    """
    parsed = urllib.parse.urlsplit(raw_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise RuntimeError("GitHub OIDC endpoint must use HTTPS")
    if not host.endswith(OIDC_HOST_SUFFIX):
        raise RuntimeError("GitHub OIDC endpoint host is not allowlisted")
    if parsed.username or parsed.password:
        raise RuntimeError("GitHub OIDC endpoint must not contain userinfo")
    if parsed.port not in (None, 443):
        raise RuntimeError("GitHub OIDC endpoint must use the standard HTTPS port")
    if not parsed.path.startswith("/"):
        raise RuntimeError("GitHub OIDC endpoint path is invalid")

    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k != "audience"]
    query.append(("audience", AUDIENCE))
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


def oidc_token() -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "").strip()
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "").strip()
    if not request_url or not request_token:
        raise RuntimeError("GitHub OIDC environment is unavailable")
    url = _validated_oidc_url(request_url)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {request_token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode("utf-8"))
    token = str(data.get("value") or "")
    if not token:
        raise RuntimeError("GitHub OIDC token response had no value")
    return token


def edge(payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        EDGE_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {oidc_token()}",
            "Content-Type": "application/json",
            "User-Agent": "tomoki-manager-queue/v1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"manager gateway HTTP {exc.code}: {body}") from exc


def risk_class(task: dict[str, Any]) -> tuple[str, str, str]:
    text = " ".join([
        str(task.get("title") or ""),
        str(task.get("instructions") or ""),
        json.dumps(task.get("context") or {}, ensure_ascii=False),
    ]).lower()
    if any(k in text for k in ("rls", "security", "permission", "credential", "secret", "external write", "external-write", "privileged", "access control")):
        return "SECURITY_OR_PRIVILEGE", "TOMOKI / SKEPTIC", "HOLD_FOR_INDEPENDENT_SECURITY_REVIEW"
    if any(k in text for k in ("backlog", "event path", "router", "consumer", "recurrent", "recurrence", "stale")):
        return "RELIABILITY_OR_RECURRENCE", "TOMOKI / HOUND", "REQUIRE_DRAIN_OR_RECOVERY_EVIDENCE"
    return "GOVERNANCE_OR_IMPLEMENTATION", "TOMOKI / FORGE", "ROUTE_FOR_BOUNDED_IMPLEMENTATION_REVIEW"


def review_package(task: dict[str, Any], worker: str) -> dict[str, Any]:
    risk, reviewer, decision = risk_class(task)
    return {
        "schema": "tomoki-manager-task-review/v1",
        "manager_stage_complete": True,
        "verified": False,
        "final_approval": False,
        "task_id": task.get("id"),
        "title": task.get("title"),
        "priority": task.get("priority"),
        "risk_class": risk,
        "decision": decision,
        "recommended_independent_reviewer": reviewer,
        "automatic_mutation_applied": False,
        "summary": (
            "Canonical MANAGER claimed the task, normalized the evidence and selected the next independent gate. "
            "The task is moved to review, not marked done."
        ),
        "evidence": {
            "claimed_by": worker,
            "owner_role": task.get("owner_role"),
            "attempt_count": task.get("attempt_count"),
            "source_runtime": task.get("source_runtime"),
            "source_task_ref": task.get("source_task_ref"),
            "context": task.get("context") or {},
            "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "github_workflow": os.environ.get("GITHUB_WORKFLOW", ""),
            "git_sha": os.environ.get("GITHUB_SHA", ""),
        },
        "guardrails": [
            "manager cannot self-verify",
            "no security/permission/credential/billing/external-write mutation at triage stage",
            "independent evidence required before done",
        ],
        "next_action": f"{reviewer} independently verifies evidence; FORGE implements only bounded approved repair; BOSS/CEO only receive material outcome.",
    }


def run_cycle(limit: int) -> dict[str, Any]:
    limit = max(1, min(3, limit))
    heartbeat = edge({"action": "heartbeat"})
    rows: list[dict[str, Any]] = []
    for _ in range(limit):
        claimed = edge({"action": "claim"})
        task = claimed.get("task")
        if not task:
            break
        worker = str(claimed.get("worker") or "")
        package = review_package(task, worker)
        try:
            completed = edge({
                "action": "complete",
                "task_id": task.get("id"),
                "worker": worker,
                "result": package,
            })
            rows.append({
                "task_id": task.get("id"),
                "title": task.get("title"),
                "priority": task.get("priority"),
                "risk_class": package["risk_class"],
                "next_gate": package["recommended_independent_reviewer"],
                "moved_to_review": bool(completed.get("completed_to_review")),
            })
        except Exception as exc:
            try:
                edge({
                    "action": "fail",
                    "task_id": task.get("id"),
                    "worker": worker,
                    "error": str(exc)[:1000],
                    "failure_fingerprint": "manager_queue_review_failed",
                })
            except Exception:
                pass
            raise
    return {
        "schema": "tomoki-manager-queue-cycle/v1",
        "runtime_id": heartbeat.get("runtime_id"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "claimed_and_reviewed": len(rows),
        "max_per_cycle": limit,
        "tasks": rows,
        "final_self_approval": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=3)
    args = parser.parse_args()
    result = run_cycle(args.max)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
