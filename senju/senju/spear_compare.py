"""Compare consecutive sanitized SPEAR assessment summaries.

Pure data-plane logic: no network access and no external authority changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _finding_map(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for target in summary.get("targets", []):
        host = str(target.get("target_host", ""))
        for finding in target.get("findings", []):
            key = str(finding.get("key", ""))
            if not host or not key:
                continue
            out[f"{host}:{key}"] = {
                "host": host,
                "key": key,
                "severity": str(finding.get("severity", "info")),
                "title": str(finding.get("title", key)),
            }
    return out


def _receipt_map(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for target in summary.get("targets", []):
        host = str(target.get("target_host", ""))
        for receipt in target.get("receipts", []):
            check = str(receipt.get("check", ""))
            if not host or not check:
                continue
            out[f"{host}:{check}"] = {
                "host": host,
                "check": check,
                "status": int(receipt.get("status", 0)),
                "response_sha256": str(receipt.get("response_sha256", "")),
            }
    return out


def compare_summaries(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current_findings = _finding_map(current)
    current_receipts = _receipt_map(current)

    if previous is None:
        return {
            "schema": "senju-spear-regression-diff/v1",
            "baseline_present": False,
            "new_findings": sorted(current_findings.values(), key=lambda x: (x["host"], x["key"])),
            "resolved_findings": [],
            "persisting_findings": [],
            "severity_changes": [],
            "response_changes": [],
            "counts": {
                "new": len(current_findings),
                "resolved": 0,
                "persisting": 0,
                "severity_up": 0,
                "severity_down": 0,
                "response_changed": 0,
            },
            "risk_direction": "baseline_created",
        }

    previous_findings = _finding_map(previous)
    previous_receipts = _receipt_map(previous)
    new_keys = sorted(set(current_findings) - set(previous_findings))
    resolved_keys = sorted(set(previous_findings) - set(current_findings))
    persisting_keys = sorted(set(current_findings) & set(previous_findings))

    severity_changes: list[dict[str, Any]] = []
    severity_up = 0
    severity_down = 0
    for composite in persisting_keys:
        before = previous_findings[composite]["severity"]
        after = current_findings[composite]["severity"]
        if before == after:
            continue
        before_rank = SEVERITY_RANK.get(before, 0)
        after_rank = SEVERITY_RANK.get(after, 0)
        direction = "up" if after_rank > before_rank else "down"
        severity_up += direction == "up"
        severity_down += direction == "down"
        severity_changes.append(
            {
                "host": current_findings[composite]["host"],
                "key": current_findings[composite]["key"],
                "before": before,
                "after": after,
                "direction": direction,
            }
        )

    response_changes: list[dict[str, Any]] = []
    for composite in sorted(set(current_receipts) & set(previous_receipts)):
        before = previous_receipts[composite]
        after = current_receipts[composite]
        status_changed = before["status"] != after["status"]
        body_changed = before["response_sha256"] != after["response_sha256"]
        if not status_changed and not body_changed:
            continue
        response_changes.append(
            {
                "host": after["host"],
                "check": after["check"],
                "status_before": before["status"],
                "status_after": after["status"],
                "status_changed": status_changed,
                "body_fingerprint_changed": body_changed,
            }
        )

    weighted_new = sum(
        SEVERITY_RANK.get(current_findings[key]["severity"], 0) + 1 for key in new_keys
    )
    weighted_resolved = sum(
        SEVERITY_RANK.get(previous_findings[key]["severity"], 0) + 1 for key in resolved_keys
    )
    delta = weighted_new + severity_up - weighted_resolved - severity_down
    if delta > 0:
        risk_direction = "worse"
    elif delta < 0:
        risk_direction = "better"
    else:
        risk_direction = "stable"

    return {
        "schema": "senju-spear-regression-diff/v1",
        "baseline_present": True,
        "new_findings": [current_findings[key] for key in new_keys],
        "resolved_findings": [previous_findings[key] for key in resolved_keys],
        "persisting_findings": [current_findings[key] for key in persisting_keys],
        "severity_changes": severity_changes,
        "response_changes": response_changes,
        "counts": {
            "new": len(new_keys),
            "resolved": len(resolved_keys),
            "persisting": len(persisting_keys),
            "severity_up": severity_up,
            "severity_down": severity_down,
            "response_changed": len(response_changes),
        },
        "risk_direction": risk_direction,
    }


def load_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("SPEAR summary must be a JSON object")
    return data


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare current SPEAR evidence with previous evidence")
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    current = load_json(args.current)
    previous = load_json(args.previous) if args.previous and Path(args.previous).exists() else None
    diff = compare_summaries(current, previous)
    Path(args.out).write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(diff, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
