from __future__ import annotations

import json
from pathlib import Path

from engine.shared_discovery_authority import run_shared_discovery_authority


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_generated_authority_and_action_receipts_never_become_discovery_sources(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "meta_discovery.json", {"url": "https://real.owner.example/"})
    _write(
        state / "discovery_capability_leases.json",
        {"schema": "meta-discovery-capability-leases/v1", "leases": [{"url": "https://lease.owner.example/"}]},
    )
    _write(
        state / "discovery_external_action_receipts.json",
        {
            "schema": "meta-discovery-external-action-receipts/v1",
            "receipts": [{"url": "https://receipt.owner.example/", "final_url": "https://receipt.owner.example/done"}],
        },
    )

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["shared_discovery_count"] == 1
    shared = json.loads((state / "shared_discovery_knowledge.json").read_text())
    assert [row["url"] for row in shared["discoveries"]] == ["https://real.owner.example/"]
