"""Cross-repository knowledge synchronization engine.

Enables real-time discovery and capability sharing between:
- test repository (TOMOKI, HOUND, SKEPTIC agents)
- the-world2 repository (SENJU, X, META agents)

Stages:
1. Knowledge sync: Discoveries are shared via unified DB
2. Unified purpose: All agents align on "supreme LLM IDE"
3. Complete organism: 150+ agents operate as single intelligence
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

KNOWLEDGE_DB = Path("automation/shared_knowledge.json")
DISCOVERY_SCHEMA = "unified-discovery-event/v1"


def load_knowledge_db() -> Dict[str, Any]:
    """Load shared knowledge database."""
    if KNOWLEDGE_DB.exists():
        with open(KNOWLEDGE_DB) as f:
            return json.load(f)
    return {"repositories": {}, "unified_targets": {}, "discoveries": []}


def save_knowledge_db(data: Dict[str, Any]) -> None:
    """Save shared knowledge database."""
    with open(KNOWLEDGE_DB, "w") as f:
        json.dump(data, f, indent=2)


def register_discovery(
    source_repo: str,
    agent_name: str,
    discovery_type: str,
    content: Dict[str, Any],
    priority: int = 50,
) -> Dict[str, Any]:
    """Register a discovery for cross-repo sharing.

    Args:
        source_repo: 'test' or 'the-world2'
        agent_name: Agent that discovered (SENJU, X, META, TOMOKI, etc)
        discovery_type: 'feature', 'optimization', 'pattern', 'capability'
        content: Discovery metadata
        priority: 1-100 (higher = share immediately)
    """
    db = load_knowledge_db()

    discovery = {
        "id": f"{source_repo}-{agent_name}-{int(time.time())}",
        "source": source_repo,
        "agent": agent_name,
        "type": discovery_type,
        "priority": priority,
        "timestamp": datetime.utcnow().isoformat(),
        "content": content,
        "status": "pending_sync",
    }

    if "discoveries" not in db:
        db["discoveries"] = []
    db["discoveries"].append(discovery)
    save_knowledge_db(db)

    return discovery


def consume_discoveries(target_repo: str) -> List[Dict[str, Any]]:
    """Get discoveries from other repos for this one.

    Args:
        target_repo: Repository that will consume ('the-world2' or 'test')

    Returns:
        List of applicable discoveries
    """
    db = load_knowledge_db()
    discoveries = db.get("discoveries", [])

    # Filter to high-priority and not-yet-synced
    applicable = [
        d for d in discoveries
        if d["source"] != target_repo
        and d["status"] == "pending_sync"
        and d["priority"] >= 40
    ]

    # Mark as synced
    for d in applicable:
        d["status"] = "synced"
    save_knowledge_db(db)

    return applicable


def align_agent_mandates() -> Dict[str, Dict[str, Any]]:
    """Align agent purposes across repos.

    Returns:
        Mandate alignments (repo -> agent -> purpose)
    """
    return {
        "the-world2": {
            "SENJU": "API reliability, performance optimization, persistence layer",
            "X": "UX/DX, GitHub integration, code generation feedback",
            "META": "Observability, model routing, metrics & telemetry",
        },
        "test": {
            "TOMOKI": "Deep forge, build/deploy verification, CI/CD",
            "HOUND": "Security testing, adversarial validation",
            "SKEPTIC": "Correctness verification, proof-of-capability",
        },
        "unified_goal": "Build the supreme LLM IDE — ultimate AI development tool",
        "unified_success_metric": "All 150+ agents working in parallel toward single goal",
    }


def stage_summary() -> Dict[str, Any]:
    """Current stage and next actions."""
    db = load_knowledge_db()

    return {
        "current_stage": "Stage 1: Knowledge Sync",
        "status": "Initializing",
        "discoveries_registered": len(db.get("discoveries", [])),
        "agents_aligned": False,
        "webhook_active": False,
        "next_actions": [
            "Enable GitHub webhooks (push events)",
            "Start registering discoveries",
            "Align agent mandates",
            "Move to Stage 2: Unified Purpose",
        ],
    }


if __name__ == "__main__":
    # Example: Register a discovery from SENJU
    discovery = register_discovery(
        source_repo="the-world2",
        agent_name="SENJU",
        discovery_type="optimization",
        content={
            "title": "Response streaming optimization",
            "description": "Implemented parallel SSE chunks",
            "applicable_to": ["test"],
        },
        priority=80,
    )
    print(f"Discovery registered: {discovery['id']}")

    # Consume available discoveries
    available = consume_discoveries("test")
    print(f"Available for test repo: {len(available)} discoveries")

    # Check alignment
    mandates = align_agent_mandates()
    print(f"Unified goal: {mandates['unified_goal']}")

    # Stage status
    status = stage_summary()
    print(f"Status: {status['status']}")
    print(f"Registered discoveries: {status['discoveries_registered']}")
