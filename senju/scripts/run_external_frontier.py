#!/usr/bin/env python3
"""Run Senju's approval-free public-web research frontier.

The frontier follows public HTTP(S) links using GET/HEAD only. Newly discovered
public hosts may be added automatically to the read scope, but discovery never
creates write/effect authority. The runner deliberately diversifies across hosts and
limits repeat visits so a larger research budget does not become a hot-loop against
one public site.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from senju.autonomy.discovery import AutonomyLoop, WorkItem


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def run_frontier(
    seed_urls: Iterable[str],
    *,
    out_dir: str | Path,
    max_steps: int = 24,
    max_host_budget: int = 32,
    max_unique_hosts: int = 24,
    max_visits_per_host: int = 2,
    delay_seconds: float = 0.0,
    client=None,  # noqa: ANN001
) -> dict[str, Any]:
    seeds = [str(url).strip() for url in seed_urls if str(url).strip()]
    if not seeds:
        raise ValueError("at least one seed URL is required")
    if not 1 <= int(max_steps) <= 100:
        raise ValueError("max_steps must be between 1 and 100")
    if not 1 <= int(max_host_budget) <= 100:
        raise ValueError("max_host_budget must be between 1 and 100")
    if not 1 <= int(max_unique_hosts) <= 64:
        raise ValueError("max_unique_hosts must be between 1 and 64")
    if not 1 <= int(max_visits_per_host) <= 8:
        raise ValueError("max_visits_per_host must be between 1 and 8")
    if not 0.0 <= float(delay_seconds) <= 2.0:
        raise ValueError("delay_seconds must be between 0 and 2 seconds")

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    loop = AutonomyLoop(
        allow_hosts=[],
        out_dir=output,
        client=client,
        max_host_budget=int(max_host_budget),
        auto_authorize_reads=True,
    )

    for index, url in enumerate(seeds, 1):
        loop.queue.enqueue(
            WorkItem(
                id=f"seed-{index}",
                item_type="discovery",
                url=url,
                method="GET",
                source="agency_seed",
                novelty_score=1.0,
                expected_research_value=0.8,
            )
        )

    results: list[dict[str, Any]] = []
    visited_urls: list[str] = []
    evidence_paths: list[str] = []
    discovered_links = 0
    contacted_hosts: set[str] = set()
    visits_per_host: dict[str, int] = {}
    skipped_unique_host_budget = 0
    skipped_repeat_host_budget = 0
    candidates_examined = 0

    while len(results) < int(max_steps):
        item = loop.queue.pop_next()
        if item is None:
            break
        candidates_examined += 1
        host = _host(item.url)
        if host and host not in contacted_hosts and len(contacted_hosts) >= int(max_unique_hosts):
            skipped_unique_host_budget += 1
            continue
        if host and visits_per_host.get(host, 0) >= int(max_visits_per_host):
            skipped_repeat_host_budget += 1
            continue

        if results and delay_seconds:
            time.sleep(float(delay_seconds))
        result = loop.execute_step(item)
        if host:
            contacted_hosts.add(host)
            visits_per_host[host] = visits_per_host.get(host, 0) + 1
        visited_urls.append(item.url)
        evidence_path = result.get("evidence_path")
        if evidence_path:
            evidence_paths.append(str(evidence_path))
        discovered_links += int(result.get("new_enqueued_candidates") or 0)
        results.append(
            {
                "url": item.url,
                "host": host,
                "success": bool(result.get("success")),
                "auto_authorized_read_host": bool(result.get("auto_authorized_read_host")),
                "auto_authorized_discovered_hosts": list(
                    result.get("auto_authorized_discovered_hosts") or []
                ),
                "new_enqueued_candidates": int(result.get("new_enqueued_candidates") or 0),
                "error": result.get("error"),
            }
        )

    successful = sum(1 for item in results if item["success"])
    summary = {
        "schema": "senju-external-frontier/v2",
        "mode": "public-read-only-autonomy",
        "seed_urls": seeds,
        "max_steps": int(max_steps),
        "max_host_budget": int(max_host_budget),
        "max_unique_hosts": int(max_unique_hosts),
        "max_visits_per_host": int(max_visits_per_host),
        "delay_seconds": float(delay_seconds),
        "candidates_examined": candidates_examined,
        "steps_executed": len(results),
        "successful_steps": successful,
        "failed_steps": len(results) - successful,
        "discovered_links_enqueued": discovered_links,
        "skipped_unique_host_budget": skipped_unique_host_budget,
        "skipped_repeat_host_budget": skipped_repeat_host_budget,
        "visited_urls": visited_urls,
        "contacted_hosts": sorted(contacted_hosts),
        "visits_per_host": dict(sorted(visits_per_host.items())),
        "read_scope_hosts": sorted(loop.allow_hosts),
        "evidence_paths": evidence_paths,
        "results": results,
        "external_write_attempted": False,
        "external_exploit_attempted": False,
    }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-url", action="append", default=[])
    ap.add_argument("--out-dir", default="reports/external-frontier")
    ap.add_argument("--out", default="reports/external-frontier.json")
    ap.add_argument("--max-steps", type=int, default=24)
    ap.add_argument("--max-host-budget", type=int, default=32)
    ap.add_argument("--max-unique-hosts", type=int, default=24)
    ap.add_argument("--max-visits-per-host", type=int, default=2)
    ap.add_argument("--delay-seconds", type=float, default=0.0)
    args = ap.parse_args()

    summary = run_frontier(
        args.seed_url,
        out_dir=args.out_dir,
        max_steps=args.max_steps,
        max_host_budget=args.max_host_budget,
        max_unique_hosts=args.max_unique_hosts,
        max_visits_per_host=args.max_visits_per_host,
        delay_seconds=args.delay_seconds,
    )
    encoded = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
