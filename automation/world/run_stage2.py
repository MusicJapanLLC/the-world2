#!/usr/bin/env python3
"""Execute Stage 2: Unified Purpose

Run this to:
1. Initialize Stage 2 across both repositories
2. Align all 150+ agents on unified goal
3. Trigger parallel execution
4. Monitor and verify completion
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Import Stage 2 orchestrator
from stage2_unified_execution import UnifiedExecutionOrchestrator


def main():
    print("=" * 70)
    print("STAGE 2: UNIFIED PURPOSE EXECUTION")
    print("=" * 70)
    print()

    orchestrator = UnifiedExecutionOrchestrator()

    # Step 1: Initialize Stage 2
    print("[1/4] Initializing Stage 2...")
    stage2_state = orchestrator.initialize_stage2()

    print(f"  ✓ Goal: {stage2_state['goal']}")
    print(f"  ✓ Repositories: {', '.join(stage2_state['repositories'])}")
    print(f"  ✓ Agents aligned: {stage2_state['metrics']['agents_aligned']}")
    print()

    # Step 2: Define unified roadmap
    print("[2/4] Creating unified roadmap...")
    roadmap = orchestrator.create_unified_llm_ide_roadmap()

    total_tasks = sum(len(phase["tasks"]) for phase in roadmap)
    print(f"  ✓ Phases: {len(roadmap)}")
    print(f"  ✓ Total tasks: {total_tasks}")

    for phase in roadmap:
        print(f"    - Phase {phase['phase']}: {phase['name']} ({len(phase['tasks'])} tasks)")

    all_tasks = []
    for phase in roadmap:
        all_tasks.extend(phase["tasks"])
    print()

    # Step 3: Trigger parallel execution
    print("[3/4] Triggering parallel execution...")
    execution_result = orchestrator.trigger_parallel_execution(all_tasks)

    print(f"  ✓ Execution started: {execution_result['execution_start']}")
    print(f"  ✓ Tasks assigned: {execution_result['total_tasks']}")
    print(f"  ✓ Agents working: {execution_result['total_agents']}")
    print(f"  ✓ Parallel execution: {execution_result['parallel_execution']}")
    print()

    # Step 4: Verify initial execution
    print("[4/4] Verifying execution status...")

    # Simulate agent work completion (in real scenario, agents execute asynchronously)
    print("  ⏳ Agents executing tasks in parallel...")
    print()

    metrics = orchestrator.get_unified_metrics()
    print("Current Metrics:")
    print(f"  Stage: {metrics['stage']}")
    print(f"  Goal: {metrics['goal']}")
    print(f"  Total agents: {metrics['total_agents']}")
    print(f"  Active tasks: {metrics['active_tasks']}")
    print(f"  Completed tasks: {metrics['completed_tasks']}")
    print(f"  Success rate: {metrics['success_rate']:.1%}")
    print(f"  Status: {metrics['status']}")
    print()

    # Write execution summary
    summary = {
        "stage": 2,
        "goal": orchestrator.goal,
        "initialized_at": stage2_state["initialized_at"],
        "execution_started_at": execution_result["execution_start"],
        "total_agents": execution_result["total_agents"],
        "total_tasks": execution_result["total_tasks"],
        "parallel_execution": True,
        "repositories": ["test", "the-world2"],
        "status": "ACTIVE - Agents executing in parallel",
        "next_steps": [
            "Monitor agent progress",
            "Verify task completion",
            "Integrate results",
            "Move to Stage 3: Complete Unified Organism",
        ],
    }

    summary_file = Path("automation/world/stage2_execution_summary.json")
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    print("=" * 70)
    print("✅ STAGE 2 INITIALIZATION COMPLETE")
    print("=" * 70)
    print()
    print("Status: 150+ agents now working in parallel")
    print(f"Goal: {orchestrator.goal}")
    print()
    print("Execution continues in background...")
    print("Check automation/world/stage2_execution_summary.json for details")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
