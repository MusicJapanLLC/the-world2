#!/usr/bin/env python3
"""Run the production evolution cycle with durable authority checkpoint recovery.

The existing production evolution runner remains the execution engine. This wrapper
restores a fingerprinted authority checkpoint into the current production envelope,
runs one generation, then persists a new authority checkpoint into the same artifact
state document.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from automation.world.authority_checkpoint import (
    AuthorityCheckpointError,
    build_authority_checkpoint,
    records_from_state,
    restore_authority_checkpoint,
)

HERE = Path(__file__).resolve().parent
BASE_RUNNER = HERE / "run_production_evolution_cycle.py"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"state document must be an object: {path}")
    return value


def _envelope_id(plan: Mapping[str, Any]) -> str:
    return str(plan.get("envelope_id") or "production-evolution-auto-cycle-v1").strip()


def _authority_lease_id(state: Mapping[str, Any]) -> str | None:
    direct = str(state.get("authority_lease_id") or "").strip()
    if direct:
        return direct
    phase_receipts = state.get("phase_receipts")
    if isinstance(phase_receipts, Mapping):
        receipt = phase_receipts.get("authority_lease")
        if isinstance(receipt, Mapping):
            lease = str(receipt.get("lease_id") or "").strip()
            if lease:
                return lease
    return None


def _dedupe_records(*groups) -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for record in group:
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(record))
    return tuple(merged)


def _prepare_restored_state(
    *,
    plan: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    prepared = dict(previous)
    checkpoint = previous.get("authority_checkpoint")
    if not isinstance(checkpoint, Mapping):
        return prepared, None

    restored = restore_authority_checkpoint(
        checkpoint,
        allowed_profiles=plan.get("allowed_authority_profiles") or (),
        envelope_id=_envelope_id(plan),
    )
    prepared["authority_profile"] = restored["authority_profile"]
    prepared["authority_lease_id"] = restored["authority_lease_id"]
    prepared["worker_authority_leases"] = restored["worker_authority_leases"]
    return prepared, restored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    state_path = Path(args.state)
    output_path = Path(args.output)
    plan = _load(plan_path)
    previous = _load(state_path)

    try:
        prepared, restored = _prepare_restored_state(plan=plan, previous=previous)
    except AuthorityCheckpointError as exc:
        raise SystemExit(f"authority checkpoint restore rejected: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="authority-checkpoint-") as temp_dir:
        recovered_state = Path(temp_dir) / "production_evolution_state.json"
        if prepared:
            recovered_state.write_text(
                json.dumps(prepared, ensure_ascii=False, indent=2, default=list) + "\n",
                encoding="utf-8",
            )

        subprocess.run(
            [
                sys.executable,
                str(BASE_RUNNER),
                "--plan",
                str(plan_path),
                "--state",
                str(recovered_state),
                "--output",
                str(output_path),
            ],
            check=True,
        )

    current = _load(output_path)
    authority_profile = str(current.get("authority_profile") or "").strip()
    if not authority_profile:
        raise SystemExit("production cycle output did not contain authority_profile")

    current_records = records_from_state(current)
    previous_records = records_from_state(previous)
    restored_records = tuple(restored.get("historical_records") or ()) if restored else ()
    records = _dedupe_records(restored_records, previous_records, current_records)

    authority_checkpoint = build_authority_checkpoint(
        envelope_id=_envelope_id(plan),
        authority_profile=authority_profile,
        authority_lease_id=_authority_lease_id(current),
        worker_authority_leases=current.get("worker_authority_leases") or (),
        records=records,
        source="production-evolution-artifact",
    )
    current["authority_checkpoint"] = authority_checkpoint
    current["authority_restore"] = {
        "restored_from_previous_checkpoint": restored is not None,
        "basis": restored.get("basis") if restored else "legacy-or-initial-state",
        "evidence_only_kinds": restored.get("evidence_only_kinds") if restored else (),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2, default=list) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "authority_checkpoint_persisted": True,
                "authority_restored": restored is not None,
                "authority_profile": authority_profile,
                "authority_lease_id": _authority_lease_id(current),
                "worker_authority_leases": current.get("worker_authority_leases") or (),
                "authority_checkpoint_fingerprint": authority_checkpoint["fingerprint"],
            },
            ensure_ascii=False,
            indent=2,
            default=list,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
