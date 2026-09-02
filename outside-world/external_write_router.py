#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "TheWorld-ExternalWriteRouter/1.0"


def load_json(path: str, default: Any) -> Any:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def compact(value: str, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def recent_keys(previous: dict[str, Any], dedupe_hours: int, now: datetime) -> set[tuple[str, str]]:
    cutoff = now - timedelta(hours=max(1, dedupe_hours))
    out: set[tuple[str, str]] = set()
    for item in previous.get("history") or []:
        at = _parse_ts(item.get("at"))
        if at and at >= cutoff and item.get("platform") and item.get("source_url"):
            out.add((str(item["platform"]), str(item["source_url"])))
    return out


def daily_count(previous: dict[str, Any], platform: str, now: datetime) -> int:
    day = now.strftime("%Y-%m-%d")
    return sum(
        1
        for item in previous.get("history") or []
        if item.get("platform") == platform
        and str(item.get("at") or "").startswith(day)
        and item.get("status") in {"POSTED", "ACCEPTED"}
    )


def credential_ready(target: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = [name for name in target.get("required_env") or [] if not os.getenv(str(name), "").strip()]
    return not missing, missing


def capable_targets(config: dict[str, Any], previous: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    out = []
    for target in config.get("platforms") or []:
        if not target.get("enabled", False):
            continue
        ready, _ = credential_ready(target)
        if not ready:
            continue
        cap = int(target.get("max_per_day", 1) or 1)
        if daily_count(previous, str(target["id"]), now) >= cap:
            continue
        out.append(target)
    return out


def choose_target(source_url: str, targets: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    available = [t for t in targets if str(t["id"]) not in used]
    if not available:
        available = targets
    if not available:
        return None
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return available[int(digest[:8], 16) % len(available)]


def render_short(finding: dict[str, Any], max_chars: int) -> str:
    title = compact(str(finding.get("title") or "External field observation"), 180)
    note = compact(str(finding.get("note") or ""), max(80, max_chars - len(title) - 100))
    source = str(finding.get("url") or "")
    body = f"THE WORLD / LIMITLESS — automated field note\n{title}\n{note}\nSource: {source}"
    return body[:max_chars]


def render_long(finding: dict[str, Any]) -> tuple[str, str]:
    title = compact(str(finding.get("title") or "External field observation"), 140)
    note = compact(str(finding.get("note") or ""), 1800)
    source = str(finding.get("url") or "")
    citizen = compact(str(finding.get("display_name") or finding.get("citizen_id") or "unknown"), 100)
    body = (
        "Automated field note from **THE WORLD** under the LIMITLESS operating doctrine.\n\n"
        f"**Observer:** {citizen}\n\n"
        f"{note}\n\n"
        f"Source: {source}\n\n"
        "This is a public research observation, not a claim of endorsement. "
        "The next cycle should verify, test, build, or reject it with evidence."
    )
    return title, body


def request_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as res:
        raw = res.read(16384).decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw[:2000]}
        return int(res.status), body


def post_github_issue(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Write to GitHub Issues using GITHUB_TOKEN — always available in Actions."""
    token = os.environ["GITHUB_TOKEN"].strip()
    repo = str(target.get("repo") or "MusicJapanLLC/test")
    title, body = render_long(finding)
    labels = list(target.get("labels") or ["the-world", "automated"])
    payload = {"title": title, "body": body, "labels": labels}
    status, response = request_json(
        f"https://api.github.com/repos/{repo}/issues",
        payload,
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    return {
        "http_status": status,
        "remote_id": response.get("number"),
        "remote_url": response.get("html_url"),
    }


def post_discord_webhook(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Write to Discord via incoming webhook."""
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"].strip()
    title, body = render_long(finding)
    source = str(finding.get("url") or "")
    payload: dict[str, Any] = {
        "username": "THE WORLD",
        "embeds": [
            {
                "title": title[:256],
                "description": body[:4096],
                "color": 0x5865F2,
                "footer": {"text": f"Source: {source}"[:2048]},
            }
        ],
    }
    status, response = request_json(webhook_url, payload, {})
    return {"http_status": status, "remote_id": response.get("id")}


def post_slack_webhook(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Write to Slack via incoming webhook."""
    webhook_url = os.environ["SLACK_WEBHOOK_URL"].strip()
    title, body = render_long(finding)
    max_body = int(target.get("max_chars", 2800) or 2800)
    payload = {
        "username": "THE WORLD",
        "icon_emoji": ":globe_with_meridians:",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body[:max_body]}},
        ],
    }
    status, response = request_json(webhook_url, payload, {})
    return {"http_status": status}


def post_appdeploy(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    token = os.environ["GITHUB_TOKEN"].strip()
    run_id = os.environ.get("WORLD_SOURCE_RUN_ID", os.environ.get("GITHUB_RUN_ID", "")).strip()
    title, body = render_long(finding)
    payload = {
        "title": title,
        "source_url": finding.get("url"),
        "citizen_id": finding.get("citizen_id"),
        "display_name": finding.get("display_name"),
        "category": finding.get("category"),
        "note": body,
        "run_id": int(run_id),
    }
    status, response = request_json(
        str(target["endpoint"]),
        payload,
        {"Authorization": f"Bearer {token}"},
    )
    return {"http_status": status, "remote_id": response.get("id") or response.get("entry_id")}


def post_devto(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    title, body = render_long(finding)
    payload = {
        "article": {
            "title": title,
            "published": True,
            "body_markdown": body,
            "tags": list(target.get("tags") or ["ai", "research"]),
        }
    }
    status, response = request_json(
        str(target.get("endpoint") or "https://dev.to/api/articles"),
        payload,
        {"api-key": os.environ["DEVTO_API_KEY"].strip()},
    )
    return {"http_status": status, "remote_id": response.get("id"), "remote_url": response.get("url")}


def post_mastodon(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ["MASTODON_BASE_URL"].rstrip("/")
    token = os.environ["MASTODON_ACCESS_TOKEN"].strip()
    text = render_short(finding, int(target.get("max_chars", 480) or 480))
    body = urllib.parse.urlencode({"status": text, "visibility": "public"}).encode("utf-8")
    key = hashlib.sha256(f"{finding.get('url')}|{text}".encode("utf-8")).hexdigest()
    req = urllib.request.Request(
        f"{base_url}/api/v1/statuses",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Idempotency-Key": key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as res:
        response = json.loads(res.read(16384).decode("utf-8", "replace") or "{}")
        return {"http_status": int(res.status), "remote_id": response.get("id"), "remote_url": response.get("url")}


def post_bluesky(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    service = os.getenv("BLUESKY_PDS_URL", "https://bsky.social").rstrip("/")
    handle = os.environ["BLUESKY_HANDLE"].strip()
    app_password = os.environ["BLUESKY_APP_PASSWORD"].strip()
    _, session = request_json(
        f"{service}/xrpc/com.atproto.server.createSession",
        {"identifier": handle, "password": app_password},
        {},
    )
    access = str(session["accessJwt"])
    did = str(session["did"])
    text = render_short(finding, int(target.get("max_chars", 280) or 280))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "repo": did,
        "collection": "app.bsky.feed.post",
        "record": {"$type": "app.bsky.feed.post", "text": text, "createdAt": now},
    }
    status, response = request_json(
        f"{service}/xrpc/com.atproto.repo.createRecord",
        payload,
        {"Authorization": f"Bearer {access}"},
    )
    return {"http_status": status, "remote_id": response.get("uri")}


def post_wordpress(finding: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ["WORDPRESS_BASE_URL"].rstrip("/")
    user = os.environ["WORDPRESS_USERNAME"].strip()
    app_password = os.environ["WORDPRESS_APP_PASSWORD"].strip()
    title, body = render_long(finding)
    token = base64.b64encode(f"{user}:{app_password}".encode("utf-8")).decode("ascii")
    payload = {"title": title, "content": body, "status": str(target.get("status") or "publish")}
    status, response = request_json(
        f"{base_url}/wp-json/wp/v2/posts",
        payload,
        {"Authorization": f"Basic {token}"},
    )
    return {"http_status": status, "remote_id": response.get("id"), "remote_url": response.get("link")}


ADAPTERS = {
    "github_issue": post_github_issue,
    "discord_webhook": post_discord_webhook,
    "slack_webhook": post_slack_webhook,
    "appdeploy": post_appdeploy,
    "devto": post_devto,
    "mastodon": post_mastodon,
    "bluesky": post_bluesky,
    "wordpress": post_wordpress,
}


def execute(events: dict[str, Any], config: dict[str, Any], previous: dict[str, Any], dry_run: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = datetime.now(timezone.utc)
    dedupe_hours = int(config.get("dedupe_hours", 72) or 72)
    max_total = int(config.get("max_total_writes_per_run", 5) or 5)
    seen = recent_keys(previous, dedupe_hours, now)
    targets = capable_targets(config, previous, now)
    used: set[str] = set()
    receipts: list[dict[str, Any]] = []

    for finding in events.get("findings") or []:
        source_url = str(finding.get("url") or "")
        if not source_url:
            continue
        eligible = [t for t in targets if (str(t["id"]), source_url) not in seen]
        target = choose_target(source_url, eligible, used)
        if target is None:
            continue
        platform = str(target["id"])
        kind = str(target["kind"])
        used.add(platform)
        receipt: dict[str, Any] = {
            "platform": platform,
            "kind": kind,
            "source_url": source_url,
            "citizen_id": finding.get("citizen_id"),
            "at": now.isoformat(),
        }
        if dry_run:
            receipt["status"] = "DRY_RUN"
        else:
            try:
                result = ADAPTERS[kind](finding, target)
                code = int(result.get("http_status") or 0)
                receipt.update(result)
                receipt["status"] = "POSTED" if 200 <= code < 300 else "ERROR"
            except Exception as exc:
                receipt["status"] = "ERROR"
                receipt["error"] = type(exc).__name__
        receipts.append(receipt)
        if len(receipts) >= max_total:
            break

    history = list(previous.get("history") or [])
    history.extend(r for r in receipts if r.get("status") in {"POSTED", "ACCEPTED"})
    cutoff = now - timedelta(days=14)
    kept = []
    for item in history:
        at = _parse_ts(item.get("at"))
        if at is None or at >= cutoff:
            kept.append(item)
    state = {
        "schema": "the-world-external-write-state/v1",
        "generated_at": now.isoformat(),
        "history": kept[-500:],
        "last_receipts": receipts,
    }
    return receipts, state


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--events", default="reality-events.json")
    p.add_argument("--config", default="outside-world/external_write_targets.json")
    p.add_argument("--previous", default="external-write-previous.json")
    p.add_argument("--out", default="external-write-receipts.json")
    p.add_argument("--state", default="external-write-state.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    events = load_json(args.events, {"findings": []})
    config = load_json(args.config, {})
    previous = load_json(args.previous, {})
    receipts, state = execute(events, config, previous, dry_run=args.dry_run)
    Path(args.out).write_text(json.dumps({"schema": "the-world-external-write-receipts/v1", "receipts": receipts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"targets_ready": len(capable_targets(config, previous, datetime.now(timezone.utc))), "receipts": receipts}, ensure_ascii=False))
    return 1 if any(r.get("status") == "ERROR" for r in receipts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
