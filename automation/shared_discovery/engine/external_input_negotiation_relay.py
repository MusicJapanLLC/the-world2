"""Relay external site intelligence into the existing negotiation lanes.

This module is coordination-only. It consolidates site metadata and unresolved
authority opportunities from Shared Discovery, Owner Frontier, and the
authorized-site accelerator into the persistent negotiation runtime.

It never performs network I/O, mints authority, handles credentials, or changes
the production authority boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

SCHEMA = "the-world-external-input-negotiation-relay/v1"
QUEUE_SCHEMA = "the-world-authority-opportunity-queue/v1"
SIGNAL_SCHEMA = "senju-owner-scope-negotiation-signals/v1"
PARTICIPANTS = ("META", "X", "SENJU", "PR-ARMY", "CLAUDE", "JULES", "OPENHANDS", "COPILOT")
ROW_KEYS = ("opportunities", "candidates", "signals", "negotiation_signals", "decisions", "requests")
SOURCE_FILES = (
    "shared_discovery_knowledge.json",
    "discovery_candidates.json",
    "owner_authority_opportunity_queue.json",
    "authority_opportunity_queue.json",
    "owner_scope_negotiation_signals.json",
    "authorized_site_authority_promotion_bus.json",
    "owner_frontier_negotiator_feed.json",
)
TERMINAL_STATUSES = {"terminal_stop", "revoked", "hard_deny", "rejected"}
SATISFIED_STATUSES = {
    "verified_owner_evidence_plus_ai_council_approved",
    "authorized",
    "promoted",
    "authorized_execution_ready",
}


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clean(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:limit]


def _host(value: Any) -> str:
    text = _clean(value, 2048).lower().rstrip(".")
    if not text:
        return ""
    if "://" in text:
        try:
            parsed = urlsplit(text)
        except ValueError:
            return ""
        if parsed.username or parsed.password:
            return ""
        text = (parsed.hostname or "").lower().rstrip(".")
    if not text or "." not in text or any(ch in text for ch in "/?#@*"):
        return ""
    labels = text.split(".")
    if not all(
        label and len(label) <= 63 and label[0].isalnum() and label[-1].isalnum()
        and all(ch.isalnum() or ch == "-" for ch in label)
        for label in labels
    ):
        return ""
    return text


def _stable(*parts: Any) -> str:
    raw = "\x1f".join(str(v) for v in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _rows(doc: Any) -> list[Mapping[str, Any]]:
    if not isinstance(doc, Mapping):
        return []
    out: list[Mapping[str, Any]] = []
    for key in ROW_KEYS:
        value = doc.get(key)
        if isinstance(value, list):
            out.extend(row for row in value if isinstance(row, Mapping))
    return out


def _status(row: Mapping[str, Any]) -> str:
    return _clean(row.get("status") or row.get("decision"), 120).lower()


def _terminal(row: Mapping[str, Any]) -> bool:
    status = _status(row)
    return bool(
        row.get("hard_deny") is True
        or row.get("revoked") is True
        or status in TERMINAL_STATUSES
        or str(row.get("decision", "")).upper() == "HARD_DENY"
    )


def _satisfied(row: Mapping[str, Any]) -> bool:
    status = _status(row)
    return bool(row.get("applied") is True or status in SATISFIED_STATUSES)


def _priority(filename: str, row: Mapping[str, Any]) -> int:
    defaults = {
        "discovery_candidates.json": 80,
        "owner_authority_opportunity_queue.json": 86,
        "authority_opportunity_queue.json": 88,
        "owner_scope_negotiation_signals.json": 94,
        "authorized_site_authority_promotion_bus.json": 96,
        "owner_frontier_negotiator_feed.json": 95,
    }
    raw = row.get("priority") or row.get("priority_score")
    try:
        score = int(float(raw))
    except (TypeError, ValueError):
        score = defaults.get(filename, 75)
    return max(1, min(score, 100))


def _terminal_hosts(source_dirs: Iterable[Path]) -> set[str]:
    blocked: set[str] = set()
    for directory in source_dirs:
        for filename in SOURCE_FILES:
            if filename == "shared_discovery_knowledge.json":
                continue
            doc = _load(directory / filename, {})
            for row in _rows(doc):
                if not _terminal(row):
                    continue
                host = _host(row.get("host") or row.get("target") or row.get("url"))
                if host:
                    blocked.add(host)
    return blocked


def _metadata(source_dirs: Iterable[Path]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for directory in source_dirs:
        doc = _load(directory / "shared_discovery_knowledge.json", {})
        rows = doc.get("discoveries", []) if isinstance(doc, Mapping) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            host = _host(row.get("host") or row.get("url"))
            if not host:
                continue
            current = meta.setdefault(host, {"urls": [], "actors": [], "sources": []})
            url = _clean(row.get("url"), 2048)
            if url and url not in current["urls"]:
                current["urls"].append(url)
            for key in ("actors", "sources"):
                values = row.get(key)
                if isinstance(values, list):
                    for value in values:
                        cleaned = _clean(value, 300)
                        if cleaned and cleaned not in current[key]:
                            current[key].append(cleaned)
    return meta


def _collect(source_dirs: Iterable[Path]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    directories = list(source_dirs)
    terminal_hosts = _terminal_hosts(directories)
    metadata = _metadata(directories)
    merged: dict[str, dict[str, Any]] = {}

    for directory in directories:
        for filename in SOURCE_FILES:
            if filename == "shared_discovery_knowledge.json":
                continue
            doc = _load(directory / filename, {})
            for row in _rows(doc):
                if filename == "discovery_candidates.json" and str(row.get("decision", "")) != "candidate_only":
                    continue
                if _terminal(row) or _satisfied(row):
                    continue
                host = _host(row.get("host") or row.get("target") or row.get("url"))
                if not host or host in terminal_hosts:
                    continue
                item = merged.setdefault(
                    host,
                    {
                        "host": host,
                        "source_files": [],
                        "source_refs": [],
                        "statuses": [],
                        "reasons": [],
                        "requested_methods": [],
                        "related_authorized_hosts": [],
                        "priority": 1,
                    },
                )
                if filename not in item["source_files"]:
                    item["source_files"].append(filename)
                ref = _clean(
                    row.get("signal_id")
                    or row.get("request_id")
                    or row.get("proposal_id")
                    or row.get("candidate_id")
                    or row.get("packet_id"),
                    240,
                )
                if ref and ref not in item["source_refs"]:
                    item["source_refs"].append(ref)
                status = _status(row)
                if status and status not in item["statuses"]:
                    item["statuses"].append(status)
                reason = _clean(row.get("reason") or row.get("requested_decision"), 400)
                if reason and reason not in item["reasons"]:
                    item["reasons"].append(reason)
                methods = row.get("requested_methods")
                if isinstance(methods, list):
                    item["requested_methods"] = sorted(
                        set(item["requested_methods"]) | {str(v).strip().upper() for v in methods if str(v).strip()}
                    )
                related = _host(row.get("related_authorized_host"))
                if related and related not in item["related_authorized_hosts"]:
                    item["related_authorized_hosts"].append(related)
                item["priority"] = max(int(item["priority"]), _priority(filename, row))

    for host, item in merged.items():
        info = metadata.get(host, {})
        item["urls"] = list(info.get("urls", []))[:8]
        item["actors"] = list(info.get("actors", []))[:16]
        item["public_sources"] = list(info.get("sources", []))[:16]
        item["priority"] = min(100, int(item["priority"]) + min(8, max(0, len(item["source_files"]) - 1) * 2))
    return merged, terminal_hosts


def _prior(runtime: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load(runtime / "external_input_negotiation_relay.json", {})
    rows = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    return {
        str(row.get("host")): row
        for row in rows if isinstance(row, Mapping) and row.get("host")
    } if isinstance(rows, list) else {}


def _merge_queue(runtime: Path, opportunities: list[Mapping[str, Any]], now: int) -> None:
    path = runtime / "authority_opportunity_queue.json"
    doc = _load(path, {})
    existing = doc.get("opportunities", []) if isinstance(doc, Mapping) else []
    by_host: dict[str, dict[str, Any]] = {}
    for row in existing if isinstance(existing, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host") or row.get("target") or row.get("url"))
        if host:
            by_host[host] = dict(row)

    for relay in opportunities:
        host = str(relay["host"])
        current = by_host.get(host, {})
        if _terminal(current):
            continue
        existing_sources = current.get("sources", [])
        if not isinstance(existing_sources, list):
            existing_sources = []
        by_host[host] = {
            **current,
            "host": host,
            "reason": relay["reason"],
            "priority": max(int(current.get("priority", 0) or 0), int(relay["priority"])),
            "requested_methods": relay["requested_methods"],
            "sources": sorted(set(existing_sources) | {"external_input_negotiation_relay"}),
            "source_refs": relay["source_refs"],
            "proposal_only": True,
            "authority_effect": "none",
            "external_action_allowed": False,
            "relay_count": relay["relay_count"],
        }

    _write(path, {
        "schema": QUEUE_SCHEMA,
        "generated_at": now,
        "producer": "external_input_negotiation_relay",
        "proposal_only": True,
        "authority_activated": False,
        "external_side_effects": False,
        "opportunities": sorted(by_host.values(), key=lambda row: (-int(row.get("priority", 0) or 0), str(row.get("host", "")))),
        "opportunity_count": len(by_host),
    })


def _merge_signals(
    runtime: Path,
    opportunities: list[Mapping[str, Any]],
    now: int,
    terminal_hosts: set[str],
) -> None:
    path = runtime / "owner_scope_negotiation_signals.json"
    doc = _load(path, {})
    existing = doc.get("signals", []) if isinstance(doc, Mapping) else []
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing if isinstance(existing, list) else []:
        if not isinstance(row, Mapping):
            continue
        host = _host(row.get("host") or row.get("target") or row.get("url"))
        if host in terminal_hosts and row.get("source") == "external_input_negotiation_relay":
            continue
        sid = _clean(row.get("signal_id"), 240)
        if sid:
            by_id[sid] = dict(row)

    for relay in opportunities:
        sid = f"external-input-relay-{_stable(relay['host'])[:18]}"
        by_id[sid] = {
            "signal_id": sid,
            "host": relay["host"],
            "requested_methods": relay["requested_methods"] or ["GET", "HEAD", "OPTIONS"],
            "reason": relay["reason"],
            "source": "external_input_negotiation_relay",
            "priority": relay["priority"],
            "relay_count": relay["relay_count"],
            "shared_with": list(PARTICIPANTS),
            "proposal_only": True,
            "authority_effect": "none",
            "external_action_allowed": False,
        }

    _write(path, {
        "schema": SIGNAL_SCHEMA,
        "generated_at": now,
        "signals": sorted(by_id.values(), key=lambda row: str(row.get("host", ""))),
    })


def run_external_input_negotiation_relay(
    runtime_dir: str | Path,
    *,
    source_dirs: Iterable[str | Path] = (),
    now: int | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    current = int(time.time()) if now is None else int(now)
    directories = [Path(p) for p in source_dirs]
    if runtime not in directories:
        directories.append(runtime)

    collected, terminal_hosts = _collect(directories)
    prior = _prior(runtime)
    opportunities: list[dict[str, Any]] = []

    for host, raw in collected.items():
        old = prior.get(host, {})
        relay_count = int(old.get("relay_count", 0) or 0) + 1
        reason = raw["reasons"][0] if raw["reasons"] else "external input relay: unresolved site information should continue through existing negotiation lanes"
        opportunities.append({
            "relay_id": f"external-input-{_stable(host)[:18]}",
            "host": host,
            "priority": min(100, int(raw["priority"]) + min(5, relay_count - 1)),
            "relay_count": relay_count,
            "source_files": sorted(raw["source_files"]),
            "source_refs": raw["source_refs"][:24],
            "statuses": raw["statuses"][:12],
            "reason": reason,
            "requested_methods": raw["requested_methods"] or ["GET", "HEAD", "OPTIONS"],
            "related_authorized_hosts": raw["related_authorized_hosts"][:8],
            "urls": raw["urls"],
            "actors": raw["actors"],
            "public_sources": raw["public_sources"],
            "handoff_targets": [
                "Owner Scope Negotiation",
                "Root Authority Negotiation",
                "Authorized Site Authority Accelerator",
                "META/X/SENJU collaboration bus",
            ],
            "coordination_permissions": {
                "may_merge_evidence": True,
                "may_raise_internal_priority": True,
                "may_publish_internal_handoff": True,
                "may_trigger_downstream_negotiation_workflows": True,
                "may_contact_external_site": False,
                "may_mint_authority": False,
            },
            "proposal_only": True,
            "authority_effect": "none",
            "external_action_allowed": False,
        })

    opportunities.sort(key=lambda row: (-int(row["priority"]), row["host"]))
    _merge_queue(runtime, opportunities, current)
    _merge_signals(runtime, opportunities, current, terminal_hosts)

    result = {
        "schema": SCHEMA,
        "generated_at": current,
        "production_coordination": True,
        "participants": list(PARTICIPANTS),
        "source_dirs": [str(p) for p in directories],
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "handoff_paths": [
            "external-input->authority_opportunity_queue->Root Authority Negotiation",
            "external-input->owner_scope_negotiation_signals->Owner Scope Negotiation",
            "authorized-site-promotion-bus->external-input-relay",
            "owner-frontier-negotiator-feed->external-input-relay",
        ],
        "internal_workflow_trigger_permission": True,
        "network_io_attempted": False,
        "credential_access": False,
        "authority_minted": False,
        "external_side_effects": False,
        "hard_deny_override": False,
    }
    _write(runtime / "external_input_negotiation_relay.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--source-dir", action="append", default=[])
    parser.add_argument("--json-out")
    args = parser.parse_args()
    result = run_external_input_negotiation_relay(args.runtime, source_dirs=args.source_dir)
    if args.json_out:
        _write(Path(args.json_out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
