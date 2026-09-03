"""Connect discovery, similarity inference, and AI consensus to one authority pipeline.

The bridge intentionally makes all three signals operational inputs instead of advisory
metadata.  Each signal can create or strengthen an Authority Candidate.  Strong signal
combinations create persistent provisional-authority records and an auto-apply-ready
queue.  A provisional record becomes live only when its target/effect is already inside
an independently owner-authorized envelope represented by the existing live discovery
authority registry.

This preserves the useful formula:

    discovery -> authority candidate
    similarity -> authority weight / provisional authority
    AI consensus -> provisional authority / activation recommendation

while preventing inferred consensus, similarity, or discovery from minting a new
unrelated production trust root by themselves.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .discovery_authorization import _load_json, _normalize_host

SCHEMA = "the-world-authority-signal-bridge/v1"
RECORD_SCHEMA = "the-world-provisional-authorities/v1"
QUEUE_SCHEMA = "the-world-signal-authority-activation-queue/v1"
CONSENSUS_RECOMMENDATIONS = {
    "route_root_candidate_to_review",
    "request_reconsideration",
}


def _intent_by_host(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "human_intent_decisions.json", {})
    rows = doc.get("decisions", []) if isinstance(doc, Mapping) else []
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        raw = row.get("host")
        if not isinstance(raw, str):
            continue
        try:
            out[_normalize_host(raw)] = row
        except ValueError:
            continue
    return out


def _similarity_score(state: Path, host: str, intent: Mapping[str, Any]) -> float:
    signals = _load_json(state / "human_intent_signals.json", {})
    mapping = signals.get("similarity_by_host", {}) if isinstance(signals, Mapping) else {}
    raw = mapping.get(host, 0.0) if isinstance(mapping, Mapping) else 0.0
    try:
        score = float(raw or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    for reason in intent.get("reasons", []) if isinstance(intent.get("reasons"), (list, tuple)) else []:
        text = str(reason)
        if text.startswith("prior_similarity:"):
            try:
                score = max(score, float(text.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
    return max(0.0, min(score, 1.0))


def _council_by_host(state: Path) -> dict[str, Mapping[str, Any]]:
    doc = _load_json(state / "authority_candidate_council.json", {})
    rows = doc.get("dossiers", []) if isinstance(doc, Mapping) else []
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        raw = row.get("host")
        if not isinstance(raw, str):
            continue
        try:
            out[_normalize_host(raw)] = row
        except ValueError:
            continue
    return out


def _consensus(dossier: Mapping[str, Any]) -> tuple[bool, int, int]:
    ballots = dossier.get("ballots", []) if isinstance(dossier, Mapping) else []
    rows = [row for row in ballots if isinstance(row, Mapping)] if isinstance(ballots, list) else []
    positive = sum(1 for row in rows if str(row.get("recommendation", "")) in CONSENSUS_RECOMMENDATIONS)
    total = len(rows)
    return positive >= 3, positive, total


def _candidate_rows(state: Path) -> list[Mapping[str, Any]]:
    doc = _load_json(state / "discovery_candidates.json", {})
    rows = doc.get("candidates", []) if isinstance(doc, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _live_hosts(state: Path) -> set[str]:
    doc = _load_json(state / "discovery_authorized.json", {})
    hosts = doc.get("hosts", {}) if isinstance(doc, Mapping) else {}
    out: set[str] = set()
    if isinstance(hosts, Mapping):
        for raw in hosts:
            try:
                out.add(_normalize_host(str(raw)))
            except ValueError:
                continue
    return out


def run_authority_signal_bridge(state_dir: str | Path, *, now: int | None = None) -> dict[str, Any]:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time()) if now is None else int(now)

    intent = _intent_by_host(state)
    council = _council_by_host(state)
    live_hosts = _live_hosts(state)

    previous_doc = _load_json(state / "provisional_authorities.json", {})
    previous_rows = previous_doc.get("records", []) if isinstance(previous_doc, Mapping) else []
    previous = {
        str(row.get("host")): row
        for row in previous_rows
        if isinstance(row, Mapping) and isinstance(row.get("host"), str)
    } if isinstance(previous_rows, list) else {}

    records: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    for candidate in _candidate_rows(state):
        raw = candidate.get("host")
        if not isinstance(raw, str):
            continue
        try:
            host = _normalize_host(raw)
        except ValueError:
            continue
        if host in seen:
            continue
        seen.add(host)

        intent_row = intent.get(host, {})
        similarity = _similarity_score(state, host, intent_row)
        consensus, positive_votes, total_votes = _consensus(council.get(host, {}))
        discovered = True

        similarity_authorizing_signal = similarity >= 0.55
        strong_similarity = similarity >= 0.80
        signal_count = int(discovered) + int(similarity_authorizing_signal) + int(consensus)

        # Every discovery enters the authority pipeline. Similarity and consensus can
        # elevate it to a persistent provisional authority, but cannot manufacture a new
        # live owner envelope.
        provisional = consensus or similarity_authorizing_signal or signal_count >= 2
        auto_apply_ready = discovered and strong_similarity and consensus
        inside_owner_envelope = host in live_hosts
        live_connected = inside_owner_envelope and provisional

        prior = previous.get(host, {})
        reconsideration_count = int(prior.get("reconsideration_count", 0) or 0) + 1
        first_seen = int(prior.get("first_seen", timestamp) or timestamp)

        record = {
            "host": host,
            "url": candidate.get("url"),
            "first_seen": first_seen,
            "last_seen": timestamp,
            "reconsideration_count": reconsideration_count,
            "signals": {
                "discovery": discovered,
                "similarity": similarity,
                "similarity_authorizing_signal": similarity_authorizing_signal,
                "ai_consensus": consensus,
                "ai_consensus_positive_votes": positive_votes,
                "ai_consensus_total_votes": total_votes,
            },
            "signal_count": signal_count,
            "authority_candidate": True,
            "provisional_authority": provisional,
            "auto_apply_ready": auto_apply_ready,
            "inside_existing_owner_envelope": inside_owner_envelope,
            "live_authority_connected": live_connected,
            "auto_execute_allowed": live_connected,
            "requested_effect": "read_only",
            "requested_methods": ["GET", "HEAD"],
            "credential_scope": "none",
            "authority_effect": "reuse_existing_owner_envelope" if live_connected else "provisional_only",
            "next_step": (
                "execute_with_existing_owner_authority"
                if live_connected
                else "auto_apply_through_independent_authority_path"
                if auto_apply_ready
                else "persist_and_reconsider"
            ),
        }
        records.append(record)
        if provisional and not live_connected:
            queue.append({
                "host": host,
                "url": candidate.get("url"),
                "status": "auto_apply_ready" if auto_apply_ready else "provisional_reconsideration",
                "signal_count": signal_count,
                "similarity": similarity,
                "ai_consensus": consensus,
                "requested_effect": "read_only",
                "requested_methods": ["GET", "HEAD"],
                "credential_scope": "none",
                "apply_without_reprompt": auto_apply_ready,
                "apply_requires_existing_or_independent_owner_authority": True,
                "created_at": timestamp,
            })

    records.sort(key=lambda row: (-int(row["signal_count"]), -float(row["signals"]["similarity"]), row["host"]))
    queue.sort(key=lambda row: (row["status"] != "auto_apply_ready", -int(row["signal_count"]), row["host"]))

    record_doc = {
        "schema": RECORD_SCHEMA,
        "generated_at": timestamp,
        "persistent": True,
        "records": records,
        "record_count": len(records),
    }
    queue_doc = {
        "schema": QUEUE_SCHEMA,
        "generated_at": timestamp,
        "mode": "signal_driven_authority_apply",
        "requests": queue,
        "request_count": len(queue),
    }
    result = {
        "schema": SCHEMA,
        "generated_at": timestamp,
        "connected": True,
        "formula": {
            "ai_consensus": "authority_provisional_and_activation_signal",
            "similarity": "authority_weight_and_provisional_signal",
            "discovery": "authority_candidate_creation_signal",
        },
        "candidate_count": len(records),
        "provisional_authority_count": sum(1 for row in records if row["provisional_authority"]),
        "auto_apply_ready_count": sum(1 for row in records if row["auto_apply_ready"]),
        "live_authority_connected_count": sum(1 for row in records if row["live_authority_connected"]),
        "persistent_reconsideration": True,
        "no_reprompt_for_auto_apply_ready": True,
        "new_unrelated_live_root_from_signals_alone": False,
        "raw_credentials_from_signals": False,
        "revocation_override_from_signals": False,
    }

    (state / "provisional_authorities.json").write_text(json.dumps(record_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (state / "signal_authority_activation_queue.json").write_text(json.dumps(queue_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (state / "authority_signal_bridge.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
