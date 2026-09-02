"""Repeated low-impact outward observation loop for owned/authorized domains.

The loop deliberately uses Senju's level-5 *operational* relaxation profile while
keeping target authorization and private-network protections intact. It adapts
within each cycle: a weak/blocked HEAD observation falls back to GET, then the
loop gathers OPTIONS and conventional public metadata paths.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from .domain_scope import relaxed_client_for_domains
from .external import ExternalContactError


FALLBACK_STATUSES = {400, 401, 403, 405, 408, 429, 500, 501, 502, 503, 504}


def _same_authorized_root(host: str, root: str) -> bool:
    host = host.strip().rstrip(".").lower()
    root = root.strip().rstrip(".").lower()
    return host == root or host.endswith("." + root)


def _join(base_url: str, path: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _observe(client: Any, method: str, url: str) -> dict[str, Any]:
    try:
        result = client.contact_with_body(url, method=method)
    except ExternalContactError as exc:
        return {"method": method, "url": url, "ok": False, "error": str(exc)}
    receipt = result.receipt
    return {
        "method": method,
        "url": url,
        "ok": True,
        "status": receipt.status,
        "final_url": receipt.final_url,
        "redirect_count": receipt.redirect_count,
        "attempt_count": receipt.attempt_count,
        "response_bytes": receipt.response_bytes,
        "response_sha256": receipt.response_sha256,
        "content_type": receipt.content_type,
    }


def run_target(raw: dict[str, Any]) -> dict[str, Any]:
    name = str(raw.get("name") or "target")
    root = str(raw.get("root") or "").strip()
    base_url = str(raw.get("base_url") or "").strip()
    if not root or not base_url:
        raise ValueError(f"{name}: root and base_url are required")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{name}: base_url must be an https URL")
    if not _same_authorized_root(parsed.hostname, root):
        raise ValueError(f"{name}: base_url host is outside its authorized root")

    client = relaxed_client_for_domains(
        [root], level=5, allowed_methods=("GET", "HEAD", "OPTIONS")
    )
    observations: list[dict[str, Any]] = []

    first = _observe(client, "HEAD", base_url)
    observations.append(first)
    first_status = int(first.get("status") or 0)
    if not first.get("ok") or first_status in FALLBACK_STATUSES:
        observations.append(_observe(client, "GET", base_url))

    observations.append(_observe(client, "OPTIONS", base_url))
    for path in ("/.well-known/security.txt", "/robots.txt"):
        observations.append(_observe(client, "GET", _join(base_url, path)))

    return {
        "name": name,
        "authorized_root": root,
        "base_url": base_url,
        "relaxation_level": 5,
        "observation_count": len(observations),
        "observations": observations,
    }


def run_config(config: dict[str, Any]) -> dict[str, Any]:
    targets = config.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty list")
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "schema": "senju-outward-loop/v1",
        "executed_at_utc": now.isoformat(timespec="seconds"),
        "mode": "authorized-domain-observation",
        "targets": [run_target(dict(item)) for item in targets],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Senju authorized outward loop")
    parser.add_argument("config", help="JSON target configuration")
    parser.add_argument("--out", default="reports/senju-outward/latest.json")
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = run_config(config)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
