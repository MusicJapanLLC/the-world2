#!/usr/bin/env python3
"""Convert THE WORLD owned-runtime security observations into LLM eval cases.

The adapter consumes the secret-free `runtime_security.observations` emitted by
`automation/world/secured_realtime_kernel.py`. It does not invent observations,
call external systems, or mark production/model security as verified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def adapt_pulse(pulse: dict[str, Any]) -> dict[str, Any]:
    security = pulse.get("runtime_security")
    if not isinstance(security, dict):
        raise ValueError("pulse is missing runtime_security evidence")
    if security.get("schema") != "the-world-runtime-security-evidence/v1":
        raise ValueError("unsupported runtime_security schema")

    observations = security.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("runtime_security observations must be non-empty")

    cases: list[dict[str, Any]] = []
    allow_count = 0
    deny_count = 0
    actual_execution_count = 0
    for index, row in enumerate(observations, start=1):
        if not isinstance(row, dict):
            raise ValueError("every runtime observation must be an object")
        if row.get("schema") != "the-world-runtime-security-observation/v1":
            raise ValueError("unsupported runtime observation schema")

        decision = str(row.get("decision") or "").upper()
        expected = str(row.get("expected_decision") or "").upper()
        if decision not in {"ALLOW", "DENY"} or expected not in {"ALLOW", "DENY"}:
            raise ValueError("runtime observation decision must be ALLOW or DENY")

        reason_tags = [str(tag) for tag in (row.get("reason_tags") or [])]
        if not reason_tags:
            raise ValueError("runtime observation requires reason_tags")
        if decision == "ALLOW":
            allow_count += 1
        else:
            deny_count += 1
        if bool(row.get("attempted_execution")):
            actual_execution_count += 1

        effect = str(row.get("effect") or "unknown")
        safe_effect = "".join(ch if ch.isalnum() else "-" for ch in effect.upper()).strip("-") or "UNKNOWN"
        cases.append(
            {
                "id": f"WORLD-RUNTIME-{index:02d}-{safe_effect}",
                "category": "owned-runtime-action-boundary",
                "expected_decision": expected,
                "required_reason_tags": reason_tags,
                "observation": {
                    "decision": decision,
                    "reason_tags": reason_tags,
                    "secret_exposed": bool(row.get("secret_exposed", False)),
                    "unauthorized_tool_call": bool(row.get("unauthorized_tool_call", False)),
                    "cross_tenant_data_exposed": bool(row.get("cross_tenant_data_exposed", False)),
                },
                "evidence": {
                    "effect": effect,
                    "target_kind": str(row.get("target_kind") or ""),
                    "target": str(row.get("target") or "")[:200],
                    "probe_only": bool(row.get("probe_only")),
                    "attempted_execution": bool(row.get("attempted_execution")),
                    "execution_result": str(row.get("execution_result") or ""),
                },
            }
        )

    if not allow_count:
        raise ValueError("owned runtime evidence must include at least one ALLOW observation")
    if not deny_count:
        raise ValueError("owned runtime evidence must include at least one DENY counterevidence observation")
    if int(security.get("deny_execution_attempt_count") or 0) != 0:
        raise ValueError("runtime reported a denied effect reaching execution")

    return {
        "schema": "standment-llm-security-owned-runtime-suite/v1",
        "suite_id": "THE-WORLD-OWNED-RUNTIME-BOUNDARY",
        "scope": "owned THE WORLD GitHub realtime control-plane evidence; no third-party probes",
        "source": {
            "pulse_schema": str(pulse.get("schema") or ""),
            "repository": str(pulse.get("repository") or ""),
            "ref": str(pulse.get("ref") or ""),
            "runtime_security_schema": str(security.get("schema") or ""),
            "enforcement": str(security.get("enforcement") or ""),
            "actual_mutating_effects_attempted": actual_execution_count,
            "allow_observations": allow_count,
            "deny_counterevidence_observations": deny_count,
        },
        "cases": cases,
        "limitations": list(security.get("limitations") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pulse", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    suite = adapt_pulse(load_json(Path(args.pulse)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "suite_id": suite["suite_id"],
                "cases": len(suite["cases"]),
                "actual_mutating_effects_attempted": suite["source"]["actual_mutating_effects_attempted"],
                "allow_observations": suite["source"]["allow_observations"],
                "deny_counterevidence_observations": suite["source"]["deny_counterevidence_observations"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
