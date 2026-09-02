#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("worker input must be a JSON object")
    return data


def adapt(worker: dict[str, Any]) -> dict[str, Any]:
    if worker.get("role") != "elite_whitehat":
        raise ValueError("elite_whitehat worker required")
    findings: list[dict[str, Any]] = []
    hypothesis = str(worker.get("hypothesis") or "").strip()
    if hypothesis:
        findings.append({
            "severity": "research",
            "title": hypothesis,
            "source": "elite_whitehat.hypothesis",
        })
    for observation in worker.get("observations") or []:
        text = str(observation).strip()
        if text:
            findings.append({
                "severity": "observation",
                "title": text,
                "source": "elite_whitehat.observations",
            })
    proposed = worker.get("proposed_change") or {}
    summary = str(proposed.get("summary") or "").strip()
    if summary:
        findings.append({
            "severity": "remediation_candidate",
            "title": summary,
            "source": "elite_whitehat.proposed_change",
        })
    if not findings:
        raise ValueError("elite_whitehat worker produced no usable research material")
    return {
        "schema": "standment-whitehat-findings/v1",
        "agent_id": worker.get("agent_id"),
        "eligible": bool(worker.get("eligible")),
        "internal_score": int(worker.get("score") or 0),
        "findings": findings,
        "counterevidence": [str(x) for x in worker.get("counterevidence") or []],
        "limitations": [str(x) for x in worker.get("limitations") or []],
        "tests": [str(x) for x in proposed.get("tests") or []],
        "verification_claimed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    result = adapt(load(args.worker))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "findings": len(result["findings"]), "verification_claimed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
