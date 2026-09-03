"""Pull shared negotiation context into Owner Scope and publish Promotion feedback.

The bridge makes the collaboration bus operational in both directions:

1. ``pull`` turns proposal-only collaboration opportunities into ephemeral Owner Scope
   negotiation signals so the current production cycle can reason about them immediately.
2. ``publish`` copies Promotion Corps and Owner Scope evidence back into the shared
   authority-opportunity runtime for Root negotiation and the other agents to consume.

It never activates authority, mints credentials, changes repository policy, or performs
network I/O. Authority decisions remain in the existing Owner Scope / Standing Authority
machinery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

VALID_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
STATE_FEEDBACK_FILES = (
    "owner_scope_negotiation_signals.json",
    "owner_scope_negotiation_result.json",
    "owner_scope_negotiation_ballots.json",
    "owner_scope_expansion_evidence.json",
    "owner_contact_ceiling_effective.json",
    "council_operational_governance_result.json",
    "council_operational_policy.json",
)
PROMOTION_FEEDBACK_FILES = (
    "promotion_packets.json",
    "execution_ready.json",
    "last_promotion_cycle.json",
)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host(value: Any) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if not host or any(ch in host for ch in "/?#@*"):
        return ""
    return host


def _methods(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ["GET", "HEAD", "OPTIONS"]
    out = sorted({str(v).strip().upper() for v in values if str(v).strip().upper() in VALID_METHODS})
    return out or ["GET", "HEAD", "OPTIONS"]


def _stable(host: str) -> str:
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:18]


def pull_shared_negotiation_context(
    bus_dir: str | Path,
    state_dir: str | Path,
    *,
    max_signals: int = 128,
    now: int | None = None,
) -> dict[str, Any]:
    bus = Path(bus_dir)
    state = Path(state_dir)
    current = int(time.time()) if now is None else int(now)
    queue = _load(bus / "authority_opportunity_queue.json", {})
    opportunities = queue.get("opportunities", []) if isinstance(queue, Mapping) else []
    evidence_doc = _load(bus / "negotiation_evidence_bundle.json", {})
    evidence_by_host = evidence_doc.get("hosts", {}) if isinstance(evidence_doc, Mapping) else {}

    signal_path = state / "owner_scope_negotiation_signals.json"
    existing_doc = _load(signal_path, {})
    existing_rows = existing_doc.get("signals", []) if isinstance(existing_doc, Mapping) else []
    by_id: dict[str, dict[str, Any]] = {}
    for raw in existing_rows if isinstance(existing_rows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        signal_id = str(raw.get("signal_id") or "").strip()
        if not signal_id:
            host = _host(raw.get("host") or raw.get("target"))
            signal_id = f"legacy-{_stable(host)}" if host else ""
        if signal_id:
            by_id[signal_id] = dict(raw)

    imported: list[dict[str, Any]] = []
    terminal_skipped = 0
    sorted_rows = [row for row in opportunities if isinstance(row, Mapping)] if isinstance(opportunities, list) else []
    sorted_rows.sort(key=lambda row: (-int(row.get("priority", 0) or 0), str(row.get("host", ""))))

    for row in sorted_rows[: max(1, min(int(max_signals), 512))]:
        host = _host(row.get("host"))
        if not host:
            continue
        evidence = evidence_by_host.get(host, {}) if isinstance(evidence_by_host, Mapping) else {}
        terminal = bool(
            row.get("hard_deny")
            or row.get("revoked")
            or (isinstance(evidence, Mapping) and evidence.get("terminal_stop"))
        )
        if terminal:
            terminal_skipped += 1
            continue
        sources = list(row.get("sources", [])) if isinstance(row.get("sources"), list) else []
        refs = list(row.get("source_refs", [])) if isinstance(row.get("source_refs"), list) else []
        statuses = list(row.get("statuses", [])) if isinstance(row.get("statuses"), list) else []
        proof_types = list(row.get("proof_types", [])) if isinstance(row.get("proof_types"), list) else []
        proof_refs = list(row.get("proof_refs", [])) if isinstance(row.get("proof_refs"), list) else []
        if isinstance(evidence, Mapping):
            sources = sorted(set(sources) | {str(v) for v in evidence.get("sources", []) if str(v)})
            refs = sorted(set(refs) | {str(v) for v in evidence.get("source_refs", []) if str(v)})
            statuses = sorted(set(statuses) | {str(v) for v in evidence.get("statuses", []) if str(v)})
            proof_types = sorted(set(proof_types) | {str(v) for v in evidence.get("proof_types", []) if str(v)})
            proof_refs = sorted(set(proof_refs) | {str(v) for v in evidence.get("proof_refs", []) if str(v)})
        signal_id = f"collab-{_stable(host)}"
        reasons = evidence.get("reasons", []) if isinstance(evidence, Mapping) and isinstance(evidence.get("reasons"), list) else []
        reason = str(reasons[0] if reasons else row.get("reason") or "shared negotiation evidence")[:400]
        signal = {
            "signal_id": signal_id,
            "host": host,
            "requested_methods": _methods(row.get("requested_methods") or (evidence.get("requested_methods") if isinstance(evidence, Mapping) else [])),
            "reason": reason,
            "priority": int(row.get("priority", 70) or 70),
            "confidence": float(row.get("confidence", 0.7) or 0.7),
            "source": "authority_collaboration_bus",
            "collaboration_sources": sources,
            "source_refs": refs[:64],
            "observed_statuses": statuses,
            "observed_proof_types": proof_types,
            "observed_proof_refs": proof_refs[:32],
            "shared_context_generated_at": current,
            "proposal_only": True,
            "authority_effect": "none",
            "hard_deny": False,
            "revoked": False,
        }
        by_id[signal_id] = signal
        imported.append(signal)

    merged = sorted(by_id.values(), key=lambda row: (-int(row.get("priority", 0) or 0), str(row.get("host", ""))))
    _write(signal_path, {
        "schema": "senju-owner-scope-negotiation-signals/v2",
        "generated_at": current,
        "signals": merged,
    })
    result = {
        "schema": "the-world-negotiation-context-import/v2",
        "generated_at": current,
        "shared_bus": str(bus),
        "state_dir": str(state),
        "imported_count": len(imported),
        "terminal_skipped_count": terminal_skipped,
        "total_signal_count": len(merged),
        "imported_hosts": [row["host"] for row in imported],
        "authority_effect": "none",
        "network_io": False,
        "credential_access": False,
    }
    _write(state / "negotiation_context_import.json", result)
    return result


def _copy_files(source: Path, destination: Path, names: tuple[str, ...]) -> list[str]:
    copied: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = source / name
        if not src.is_file():
            continue
        dst = destination / name
        shutil.copyfile(src, dst)
        copied.append(name)
    return copied


def publish_promotion_feedback(
    bus_dir: str | Path,
    promotion_dir: str | Path,
    *,
    state_dir: str | Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    bus = Path(bus_dir)
    promotion = Path(promotion_dir)
    state = Path(state_dir) if state_dir else None
    current = int(time.time()) if now is None else int(now)
    copied = _copy_files(promotion, bus, PROMOTION_FEEDBACK_FILES)
    if state is not None:
        copied.extend(_copy_files(state, bus, STATE_FEEDBACK_FILES))
    result = {
        "schema": "the-world-promotion-feedback-publish/v2",
        "generated_at": current,
        "shared_bus": str(bus),
        "promotion_dir": str(promotion),
        "copied_files": sorted(set(copied)),
        "feedback_available_to": ["META", "X", "SENJU", "PR-ARMY", "CHILD", "AI", "Root Authority Negotiation"],
        "authority_effect": "none",
        "network_io": False,
        "credential_access": False,
    }
    _write(bus / "promotion_feedback_publish.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pull = sub.add_parser("pull")
    pull.add_argument("--bus-dir", required=True)
    pull.add_argument("--state-dir", required=True)
    pull.add_argument("--max-signals", type=int, default=128)
    pull.add_argument("--json-out")

    publish = sub.add_parser("publish")
    publish.add_argument("--bus-dir", required=True)
    publish.add_argument("--promotion-dir", required=True)
    publish.add_argument("--state-dir")
    publish.add_argument("--json-out")

    args = parser.parse_args()
    if args.command == "pull":
        result = pull_shared_negotiation_context(
            args.bus_dir,
            args.state_dir,
            max_signals=args.max_signals,
        )
    else:
        result = publish_promotion_feedback(
            args.bus_dir,
            args.promotion_dir,
            state_dir=args.state_dir,
        )
    if args.json_out:
        _write(Path(args.json_out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
