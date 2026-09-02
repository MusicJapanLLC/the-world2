#!/usr/bin/env python3
"""Isolated experimentation runner for THE WORLD.

Supports mutations, benchmarks, fault injections, refactors, evidence collection,
and automatic rollback state tracking inside owned sandbox/staging scope.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

EXPERIMENTS_DIR = Path("automation/world/experiments")


@dataclass
class ExperimentResult:
    experiment_id: str
    name: str
    scope: str
    success: bool
    evidence: dict[str, Any]
    duration_ms: int
    rollback_applied: bool
    artifact_path: str


def run_experiment(
    name: str,
    scope: str,
    experiment_fn: Callable[[], dict[str, Any]],
    rollback_fn: Callable[[], None] | None = None,
) -> ExperimentResult:
    experiment_id = f"exp_{int(time.time())}_{abs(hash(name)) % 10000}"
    start_time = time.time()
    evidence: dict[str, Any] = {}
    success = False
    rollback_applied = False

    try:
        evidence = experiment_fn()
        success = evidence.get("success", True)
    except Exception as exc:
        evidence = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "success": False,
        }
        success = False

    if not success and rollback_fn is not None:
        try:
            rollback_fn()
            rollback_applied = True
            evidence["rollback_status"] = "SUCCESS"
        except Exception as rb_exc:
            evidence["rollback_error"] = str(rb_exc)
            evidence["rollback_status"] = "FAILED"

    duration_ms = int((time.time() - start_time) * 1000)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = str(EXPERIMENTS_DIR / f"{experiment_id}.json")

    result = ExperimentResult(
        experiment_id=experiment_id,
        name=name,
        scope=scope,
        success=success,
        evidence=evidence,
        duration_ms=duration_ms,
        rollback_applied=rollback_applied,
        artifact_path=artifact_path,
    )

    Path(artifact_path).write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    def dummy_exp():
        return {"throughput_op_s": 1250, "success": True}

    res = run_experiment("throughput_benchmark", "automation/world", dummy_exp)
    print(asdict(res))
