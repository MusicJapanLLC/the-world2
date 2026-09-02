#!/usr/bin/env python3
"""Run META/X self-governance experiments against shadow control state."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "senju"))

from senju.meta.self_governance_lab import (  # noqa: E402
    default_workspace,
    mutate_control,
    run_matrix,
    save_workspace,
)

STATE_DIR = REPO_ROOT / "senju" / "state"


def _load_workspace(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default_workspace()
    except (OSError, json.JSONDecodeError):
        return default_workspace()


def main() -> int:
    parser = argparse.ArgumentParser(description="META/X isolated self-governance control lab")
    parser.add_argument("--actor", choices=["META", "X"], required=True)
    parser.add_argument("--environment", default="sandbox")
    parser.add_argument("--control")
    parser.add_argument("--operation")
    parser.add_argument("--payload-json", default="{}")
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    actor = args.actor.upper()

    if args.matrix:
        report = run_matrix(actor=actor, environment=args.environment)
        out = STATE_DIR / f"{actor.lower()}_self_governance_matrix.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "actor": actor,
            "environment": args.environment,
            "experiments": report["experiments"],
            "runtime_binding_modified": report["runtime_binding_modified"],
            "output": str(out),
        }, ensure_ascii=False))
        return 0

    if not args.control or not args.operation:
        parser.error("--control and --operation are required unless --matrix is used")

    try:
        payload = json.loads(args.payload_json)
    except json.JSONDecodeError as exc:
        parser.error(f"invalid --payload-json: {exc}")
    if not isinstance(payload, dict):
        parser.error("--payload-json must decode to an object")

    workspace_path = STATE_DIR / f"{actor.lower()}_self_governance_workspace.json"
    workspace = _load_workspace(workspace_path)
    result = mutate_control(
        workspace,
        actor=actor,
        environment=args.environment,
        control=args.control,
        operation=args.operation,
        payload=payload,
    )
    save_workspace(workspace_path, workspace)
    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
