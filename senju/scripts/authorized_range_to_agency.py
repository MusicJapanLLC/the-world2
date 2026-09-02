#!/usr/bin/env python3
"""Convert a Senju authorized-range closed-loop report into agency-bus memory.

The adapter is deliberately boring: it does not execute network operations.
It turns verified closed-loop observations into the existing owned-range schema
consumed by ``scripts/agency_bus.py`` so findings, confirmations and adaptive
probe rankings survive into later Senju cycles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class AgencyBridgeError(RuntimeError):
    """Raised when an input report cannot be safely normalized."""


def _stable_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()[:24]


def _probe_family_by_fingerprint(report: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    shares = report.get("finding_shares") or []
    if not isinstance(shares, list):
        return out
    for raw in shares:
        if not isinstance(raw, Mapping):
            continue
        fingerprint = str(raw.get("fingerprint") or "")
        family = str(raw.get("probe_family") or "")
        if fingerprint and family:
            out[fingerprint] = family
    return out


def _counterexamples(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("findings") or []
    if not isinstance(rows, list):
        raise AgencyBridgeError("findings must be a list")
    family_by_fp = _probe_family_by_fingerprint(report)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        fingerprint = str(raw.get("fingerprint") or "")
        category = str(raw.get("category") or "authorized_range_observation")[:120]
        url = str(raw.get("url") or "")[:500]
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), Mapping) else {}
        identity = fingerprint or hashlib.sha256(
            f"{category}\n{url}\n{json.dumps(evidence, sort_keys=True, default=str)}".encode("utf-8")
        ).hexdigest()[:20]
        if identity in seen:
            continue
        seen.add(identity)
        out.append(
            {
                "kind": category,
                "target": url,
                "probe": family_by_fp.get(fingerprint, "authorized_range_closed_loop"),
                "outcome": str(raw.get("status") or "observed")[:120],
                "reason": json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)[:500],
                "severity": str(raw.get("severity") or "info")[:40],
                "confidence": raw.get("confidence"),
                "fingerprint": identity,
                "observations": int(raw.get("observations") or 1),
            }
        )
    return out


def convert_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("schema") != "senju-authorized-range-closed-loop/v2":
        raise AgencyBridgeError("unsupported authorized-range report schema")
    host = str(report.get("exact_host") or "").strip().lower()
    if not host:
        raise AgencyBridgeError("exact_host is required")
    if report.get("same_origin_only") is not True:
        raise AgencyBridgeError("agency bridge accepts same-origin-only reports")
    if report.get("destructive") is not False:
        raise AgencyBridgeError("agency bridge accepts non-destructive reports only")

    cycles = report.get("cycles") or []
    last_cycle = cycles[-1] if isinstance(cycles, list) and cycles and isinstance(cycles[-1], Mapping) else {}
    ranking = last_cycle.get("probe_ranking_next") or []
    if not isinstance(ranking, list):
        ranking = []
    counterexamples = _counterexamples(report)

    packet: dict[str, Any] = {
        "schema": "senju-owned-range-active/v2",
        "authorized_host": host,
        "request_count": int(report.get("request_count") or 0),
        "pages_discovered": int(report.get("pages_observed") or 0),
        "forms_discovered": sum(
            1
            for row in counterexamples
            if row.get("kind") in {"state_form_without_visible_csrf_hint", "cross_origin_form_action"}
        ),
        "write_attempts": 0,
        "write_provider_acks": 0,
        "independent_readbacks": 0,
        "blocked_out_of_scope": int(report.get("blocked_out_of_scope") or 0),
        "counterexample_count": len(counterexamples),
        "counterexamples": counterexamples,
        "evolution": {
            "next_family_ranking": [str(item)[:80] for item in ranking[:12]],
            "cycles_completed": len(cycles) if isinstance(cycles, list) else 0,
            "scheduler": report.get("scheduler") if isinstance(report.get("scheduler"), Mapping) else {},
        },
    }
    packet["digest"] = _stable_digest(packet)
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge authorized-range evidence into Senju agency memory")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AgencyBridgeError("report must be a JSON object")
    packet = convert_report(raw)
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "digest": packet["digest"],
                "authorized_host": packet["authorized_host"],
                "counterexample_count": packet["counterexample_count"],
                "next_family_ranking": packet["evolution"]["next_family_ranking"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
