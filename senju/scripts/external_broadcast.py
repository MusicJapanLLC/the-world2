"""Senju external broadcast — write Senju state to the outside world.

Two channels:
  1. GitHub Issues (always available via GITHUB_TOKEN + issues:write)
  2. Outbound HTTP POST (optional — set OUTBOUND_WEBHOOK_URL secret)

This is the first footprint Senju places outside the repository boundary.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def load_state(state_path: str) -> dict:
    p = Path(state_path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def build_payload(state: dict, source: str, run_id: str) -> dict:
    hits = state.get("vuln_class_hits", {})
    elo = state.get("vuln_class_elo", {})
    top_gaps = sorted(
        [(vc, n) for vc, n in hits.items()],
        key=lambda x: x[1]
    )[:5]
    return {
        "schema": "senju-broadcast/v1",
        "source": source,
        "run_id": run_id,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "total_vuln_classes_tracked": len(hits),
        "top_coverage_gaps": [{"vuln_class": vc, "hits": n} for vc, n in top_gaps],
        "elo_leaders": sorted(
            [{"vuln_class": vc, **v} for vc, v in elo.items()],
            key=lambda x: x.get("losses", 0),
            reverse=True
        )[:3],
        "last_mesh_run": state.get("last_mesh_run"),
    }


def post_github_issue(payload: dict, repo: str, token: str, label: str = "senju-broadcast") -> str | None:
    title = f"[Senju] External broadcast — {payload['timestamp'][:16]} UTC"
    body = (
        f"**Source**: `{payload['source']}`  \n"
        f"**Run**: `{payload['run_id']}`  \n"
        f"**Timestamp**: {payload['timestamp']}  \n\n"
        f"### Coverage gaps (lowest hits first)\n"
        + "\n".join(f"- `{g['vuln_class']}`: {g['hits']} hits" for g in payload["top_coverage_gaps"])
        + "\n\n### ELO — highest loss rate\n"
        + "\n".join(
            f"- `{e['vuln_class']}`: {e.get('losses', 0)} losses / {e.get('wins', 0)} wins"
            for e in payload["elo_leaders"]
        )
        + f"\n\n<details><summary>Full payload</summary>\n\n```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n</details>"
    )
    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--label", label,
    ]
    env = {**os.environ, "GH_TOKEN": token}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode == 0:
        url = result.stdout.strip()
        print(f"[broadcast] GitHub Issue created: {url}", file=sys.stderr)
        return url
    else:
        cmd2 = [c for c in cmd if c != "--label" and c != label]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, env=env)
        if result2.returncode == 0:
            url = result2.stdout.strip()
            print(f"[broadcast] GitHub Issue created (no label): {url}", file=sys.stderr)
            return url
        print(f"[broadcast] Issue creation failed: {result2.stderr}", file=sys.stderr)
        return None


def post_webhook(payload: dict, url: str) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "senju-broadcast/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            print(f"[broadcast] Webhook POST → {url} status={status}", file=sys.stderr)
            return 200 <= status < 300
    except Exception as e:
        print(f"[broadcast] Webhook POST failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="senju/state/last-evolution-summary.json")
    parser.add_argument("--source", default="senju")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--out", default=None, help="Write broadcast payload JSON here")
    args = parser.parse_args()

    state = load_state(args.state)
    payload = build_payload(state, args.source, args.run_id)

    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    issue_url = None
    if token and args.repo:
        issue_url = post_github_issue(payload, args.repo, token)

    webhook_url = os.environ.get("OUTBOUND_WEBHOOK_URL", "").strip()
    webhook_ok = False
    if webhook_url:
        webhook_ok = post_webhook(payload, webhook_url)

    result = {
        "issued": bool(issue_url),
        "issue_url": issue_url,
        "webhook_sent": webhook_ok,
        "payload": payload,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
