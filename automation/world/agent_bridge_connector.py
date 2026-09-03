"""Agent Bridge Connector

Connects the-world2 agents (SENJU, X, META) with test agents (TOMOKI, HOUND, SKEPTIC)
through actual data exchange using the production evolution loop pattern.

Enables:
- Real-time discovery sharing
- Cross-repo task assignment
- Parallel execution verification
- Unified result aggregation
"""

import json
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional


class AgentBridgeConnector:
    """Bridges agent systems across repositories."""

    def __init__(self):
        self.repo_local = "the-world2"
        self.repo_remote = "test"
        self.bridge_state_file = Path("automation/world/agent_bridge_state.json")
        self.task_exchange_file = Path("automation/world/task_exchange_queue.json")
        self.discovery_sync_file = Path("automation/world/discovery_sync.json")

    def initialize_bridge(self) -> Dict[str, Any]:
        """Initialize the agent bridge connection."""
        state = {
            "bridge_initialized": True,
            "initialized_at": datetime.utcnow().isoformat(),
            "local_repo": self.repo_local,
            "remote_repo": self.repo_remote,
            "agent_mapping": {
                "the-world2": {
                    "SENJU": "API optimization & persistence",
                    "X": "UX/DX & code generation",
                    "META": "Observability & routing",
                },
                "test": {
                    "TOMOKI": "Deep forge & build verification",
                    "HOUND": "Security & adversarial testing",
                    "SKEPTIC": "Correctness verification",
                },
            },
            "bridge_capabilities": [
                "discovery_sharing",
                "task_assignment",
                "result_aggregation",
                "parallel_verification",
                "cross_repo_coordination",
            ],
            "sync_protocol": "production-evolution-envelope-v1",
            "status": "BRIDGE ACTIVE",
        }

        self._save_state(state, self.bridge_state_file)
        return state

    def register_discovery_from_agent(
        self,
        source_repo: str,
        agent_name: str,
        discovery_type: str,
        content: Dict[str, Any],
        priority: int = 50,
    ) -> Dict[str, Any]:
        """
        Agent registers a discovery for cross-repo sharing.

        Example:
        - SENJU discovers: "Parallel SSE streaming optimization"
        - Automatically shared to test repo
        - TOMOKI can use it for verification
        """
        discovery = {
            "discovery_id": f"{source_repo}-{agent_name}-{int(time.time())}",
            "source_repo": source_repo,
            "agent_name": agent_name,
            "type": discovery_type,
            "priority": priority,
            "timestamp": datetime.utcnow().isoformat(),
            "content": content,
            "status": "pending_cross_repo_verification",
            "hash": self._hash_discovery(content),
        }

        # Load sync file
        sync_data = self._load_or_create(self.discovery_sync_file, {"discoveries": []})
        sync_data["discoveries"].append(discovery)
        self._save_state(sync_data, self.discovery_sync_file)

        print(
            f"✓ Discovery registered: {agent_name} ({source_repo}) → {discovery_type}"
        )
        return discovery

    def assign_cross_repo_task(
        self,
        task_id: str,
        description: str,
        primary_agent: str,
        primary_repo: str,
        verification_agents: List[tuple[str, str]],  # [(agent_name, repo), ...]
        priority: int = 50,
    ) -> Dict[str, Any]:
        """
        Assign a task that spans multiple repos.

        Example:
        - Task: "Implement parallel code generation"
        - Primary: SENJU (the-world2)
        - Verification: TOMOKI (test), SKEPTIC (test)
        """
        task = {
            "task_id": task_id,
            "description": description,
            "primary": {
                "agent": primary_agent,
                "repo": primary_repo,
            },
            "verifiers": [
                {"agent": agent, "repo": repo}
                for agent, repo in verification_agents
            ],
            "priority": priority,
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending_execution",
            "stages": {
                "assignment": "complete",
                "primary_execution": "pending",
                "cross_repo_verification": "pending",
                "result_aggregation": "pending",
            },
        }

        # Load task queue
        queue_data = self._load_or_create(self.task_exchange_file, {"tasks": []})
        queue_data["tasks"].append(task)
        self._save_state(queue_data, self.task_exchange_file)

        print(f"✓ Cross-repo task assigned: {task_id}")
        print(f"  Primary: {primary_agent} ({primary_repo})")
        print(
            f"  Verifiers: {', '.join(f'{a}({r})' for a, r in verification_agents)}"
        )

        return task

    def execute_task_stage(
        self,
        task_id: str,
        stage: str,
        agent_name: str,
        repo: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a single stage of a task and record result.

        Stages:
        1. primary_execution: Main agent does the work
        2. cross_repo_verification: Verifiers check the result
        3. result_aggregation: Combine all results
        """
        queue_data = self._load_or_create(self.task_exchange_file, {"tasks": []})

        task = next((t for t in queue_data["tasks"] if t["task_id"] == task_id), None)
        if not task:
            return {"error": f"Task {task_id} not found"}

        # Record stage execution
        if "executions" not in task:
            task["executions"] = []

        execution = {
            "stage": stage,
            "agent": agent_name,
            "repo": repo,
            "result": result,
            "executed_at": datetime.utcnow().isoformat(),
            "status": "complete",
        }

        task["executions"].append(execution)
        task["stages"][stage] = "complete"

        # Update task status
        all_stages_complete = all(
            status == "complete" for status in task["stages"].values()
        )
        task["status"] = "complete" if all_stages_complete else "in_progress"

        self._save_state(queue_data, self.task_exchange_file)

        print(f"✓ Stage executed: {task_id}/{stage} by {agent_name}({repo})")

        return execution

    def verify_cross_repo_consistency(self, task_id: str) -> Dict[str, Any]:
        """
        Verify that results from different repos are consistent.

        Used after all verification agents complete.
        """
        queue_data = self._load_or_create(self.task_exchange_file, {"tasks": []})
        task = next((t for t in queue_data["tasks"] if t["task_id"] == task_id), None)

        if not task:
            return {"error": f"Task {task_id} not found"}

        executions = task.get("executions", [])
        verification_results = [e for e in executions if e["stage"] == "cross_repo_verification"]

        # Check for consistency
        all_passed = all(
            result.get("result", {}).get("passed", False)
            for result in verification_results
        )

        consistency = {
            "task_id": task_id,
            "verification_count": len(verification_results),
            "all_passed": all_passed,
            "consistency": "VERIFIED" if all_passed else "FAILED",
            "verified_at": datetime.utcnow().isoformat(),
        }

        task["verification_result"] = consistency

        self._save_state(queue_data, self.task_exchange_file)

        return consistency

    def sync_discoveries_to_remote(self) -> Dict[str, Any]:
        """
        Prepare discoveries for sync to remote repo.

        In real implementation, this would:
        1. Hash discoveries
        2. Create webhook payload
        3. POST to remote webhook
        4. Verify receipt
        """
        sync_data = self._load_or_create(self.discovery_sync_file, {"discoveries": []})

        pending = [
            d
            for d in sync_data.get("discoveries", [])
            if d.get("status") == "pending_cross_repo_verification"
        ]

        sync_payload = {
            "source_repo": self.repo_local,
            "target_repo": self.repo_remote,
            "discoveries": pending,
            "sync_timestamp": datetime.utcnow().isoformat(),
            "sync_id": f"sync-{int(time.time())}",
        }

        # Mark as synced
        for discovery in pending:
            discovery["status"] = "synced"
            discovery["synced_at"] = datetime.utcnow().isoformat()

        self._save_state(sync_data, self.discovery_sync_file)

        print(f"✓ Sync prepared: {len(pending)} discoveries ready for {self.repo_remote}")

        return sync_payload

    def get_bridge_status(self) -> Dict[str, Any]:
        """Get current bridge status and metrics."""
        bridge_state = self._load_or_create(self.bridge_state_file, {})
        sync_data = self._load_or_create(self.discovery_sync_file, {"discoveries": []})
        queue_data = self._load_or_create(self.task_exchange_file, {"tasks": []})

        status = {
            "bridge_initialized": bridge_state.get("bridge_initialized", False),
            "local_repo": self.repo_local,
            "remote_repo": self.repo_remote,
            "discoveries": {
                "total": len(sync_data.get("discoveries", [])),
                "pending_sync": len(
                    [
                        d
                        for d in sync_data.get("discoveries", [])
                        if d.get("status") == "pending_cross_repo_verification"
                    ]
                ),
                "synced": len(
                    [
                        d
                        for d in sync_data.get("discoveries", [])
                        if d.get("status") == "synced"
                    ]
                ),
            },
            "tasks": {
                "total": len(queue_data.get("tasks", [])),
                "in_progress": len(
                    [t for t in queue_data.get("tasks", []) if t.get("status") == "in_progress"]
                ),
                "complete": len(
                    [t for t in queue_data.get("tasks", []) if t.get("status") == "complete"]
                ),
            },
            "status": "BRIDGE ACTIVE",
        }

        return status

    def _hash_discovery(self, content: Dict[str, Any]) -> str:
        """Hash discovery content for deduplication."""
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def _load_or_create(
        self, file_path: Path, default: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Load file or return default."""
        if file_path.exists():
            with open(file_path) as f:
                return json.load(f)
        return default

    def _save_state(self, state: Dict[str, Any], file_path: Path) -> None:
        """Save state to file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(state, f, indent=2)


def run_bridge_demo():
    """Demonstrate agent bridge in action."""
    print("\n" + "=" * 70)
    print("AGENT BRIDGE CONNECTOR — Cross-Repo Agent Coordination")
    print("=" * 70 + "\n")

    bridge = AgentBridgeConnector()

    # Step 1: Initialize bridge
    print("[1/5] Initializing bridge...")
    bridge_state = bridge.initialize_bridge()
    print(f"  ✓ Bridge active: {bridge_state['status']}\n")

    # Step 2: SENJU discovers optimization
    print("[2/5] SENJU discovers parallel execution optimization...")
    discovery = bridge.register_discovery_from_agent(
        source_repo="the-world2",
        agent_name="SENJU",
        discovery_type="optimization",
        content={
            "title": "Parallel SSE streaming",
            "description": "Send chunks in parallel instead of sequential",
            "benchmark": "5x faster",
        },
        priority=90,
    )
    print()

    # Step 3: Assign cross-repo task
    print("[3/5] Assigning cross-repo task...")
    task = bridge.assign_cross_repo_task(
        task_id="llm-core-001",
        description="Implement parallel code generation with verification",
        primary_agent="SENJU",
        primary_repo="the-world2",
        verification_agents=[("TOMOKI", "test"), ("SKEPTIC", "test")],
        priority=95,
    )
    print()

    # Step 4: Execute task stages
    print("[4/5] Executing task stages...")

    # SENJU executes
    bridge.execute_task_stage(
        task_id="llm-core-001",
        stage="primary_execution",
        agent_name="SENJU",
        repo="the-world2",
        result={"code_generated": 2500, "status": "success"},
    )

    # TOMOKI verifies
    bridge.execute_task_stage(
        task_id="llm-core-001",
        stage="cross_repo_verification",
        agent_name="TOMOKI",
        repo="test",
        result={"passed": True, "tests_passing": 98},
    )

    # SKEPTIC verifies
    bridge.execute_task_stage(
        task_id="llm-core-001",
        stage="cross_repo_verification",
        agent_name="SKEPTIC",
        repo="test",
        result={"passed": True, "proof_verified": True},
    )

    print()

    # Step 5: Verify consistency
    print("[5/5] Verifying cross-repo consistency...")
    consistency = bridge.verify_cross_repo_consistency("llm-core-001")
    print(f"  ✓ Result: {consistency['consistency']}\n")

    # Show status
    print("Bridge Status:")
    status = bridge.get_bridge_status()
    print(json.dumps(status, indent=2))
    print()

    return bridge


if __name__ == "__main__":
    bridge = run_bridge_demo()
