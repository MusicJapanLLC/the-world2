#!/usr/bin/env python3
"""Read active production-authorized hosts and turn responses into next-cycle evidence.

The caller supplies a runtime policy that was already derived from explicit authority.
This script performs bounded GETs only to active hosts in that policy, extracts HTTP(S)
links from returned HTML/text, and emits them as evidence. The policy engine remains
responsible for deciding whether each discovered host inherits existing authority or is
held for a separate authority decision.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from senju.external import ExternalContactClient, ExternalContactPolicy

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() in {"href", "src", "action"} and value:
                self.links.append(value)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _active(doc: dict[str, Any], now: int) -> list[dict[str, Any]]:
    grants = doc.get("grants", {})
    rows: list[dict[str, Any]] = []
    if not isinstance(grants, dict):
        return rows
    for host, grant in grants.items():
        if not isinstance(grant, dict):
            continue
        if int(grant.get("expires_at", 0)) <= now:
            continue
        if str(grant.get("credential_scope", "none")) != "none":
            continue
        methods = {str(x).upper() for x in grant.get("allowed_methods", [])}
        if "GET" not in methods:
            continue
        rows.append({**grant, "host": str(host)})
    rows.sort(key=lambda row: row["host"])
    return rows


def _extract_links(base_url: str, text: str, content_type: str | None) -> list[str]:
    raw: list[str] = []
    if "html" in (content_type or "").lower():
        parser = _LinkParser()
        try:
            parser.feed(text)
        except Exception:
            pass
        raw.extend(parser.links)
    raw.extend(URL_RE.findall(text))

    out: set[str] = set()
    for item in raw:
        try:
            joined = urllib.parse.urljoin(base_url, item.strip())
            parsed = urllib.parse.urlsplit(joined)
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                continue
            if parsed.username is not None or parsed.password is not None:
                continue
            if parsed.port not in (None, 443):
                continue
            normalized = urllib.parse.urlunsplit(
                ("https", parsed.hostname.lower().rstrip("."), parsed.path or "/", parsed.query, "")
            )
            out.add(normalized)
        except Exception:
            continue
    return sorted(out)


def run_discovery(doc: dict[str, Any], *, max_hosts: int = 16) -> dict[str, Any]:
    now = int(time.time())
    active = _active(doc, now)[: max(0, min(int(max_hosts), 48))]
    allowed_hosts = sorted({row["host"] for row in active})
    findings: list[dict[str, Any]] = []
    fetches: list[dict[str, Any]] = []

    if allowed_hosts:
        policy = ExternalContactPolicy.from_hosts(
            allowed_hosts,
            allow_http=False,
            allow_delete=False,
            follow_redirects=True,
            max_redirects=3,
            timeout_seconds=7.5,
            max_response_bytes=256 * 1024,
            retries=1,
        )
        client = ExternalContactClient(policy)
        for grant in active:
            host = grant["host"]
            url = str(grant.get("url") or f"https://{host}/")
            try:
                result = client.contact_with_body(url, method="GET")
                text = result.text()
                links = _extract_links(result.receipt.final_url, text, result.receipt.content_type)
                fetches.append(
                    {
                        "host": host,
                        "url": url,
                        "success": bool(result.receipt.provider_acknowledged),
                        "status": result.receipt.status,
                        "final_url": result.receipt.final_url,
                        "discovered_links": len(links),
                    }
                )
                for link in links:
                    parsed = urllib.parse.urlsplit(link)
                    findings.append(
                        {
                            "url": link,
                            "host": (parsed.hostname or "").lower(),
                            "source": f"authorized_external_response:{host}",
                            "finding": "host_or_endpoint_discovered_from_authorized_response",
                        }
                    )
            except Exception as exc:
                fetches.append(
                    {
                        "host": host,
                        "url": url,
                        "success": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )

    return {
        "schema": "meta-network-policy-authorized-response-evidence/v1",
        "production": True,
        "generated_at": now,
        "source": "active_runtime_network_policy",
        "fetches": fetches,
        "findings": findings,
        "discovered_urls": [row["url"] for row in findings],
        "contacted_hosts": allowed_hosts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="automation/codegen/meta_state/network_policy_runtime.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-hosts", type=int, default=16)
    args = ap.parse_args()

    doc = _load(Path(args.policy))
    result = run_discovery(doc, max_hosts=args.max_hosts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "contacted_hosts": len(result["contacted_hosts"]),
                "successful_fetches": sum(1 for row in result["fetches"] if row.get("success")),
                "discovered_urls": len(result["discovered_urls"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
