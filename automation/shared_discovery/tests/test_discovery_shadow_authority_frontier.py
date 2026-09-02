from __future__ import annotations

import json
from pathlib import Path

from engine.discovery_shadow_authority_frontier import build_shadow_frontier


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_frontier_explores_all_five_without_production_effect(tmp_path: Path) -> None:
    _write(
        tmp_path / "discovery_candidates.json",
        {"candidates": [{"url": "https://outside.example/path"}]},
    )
    result = build_shadow_frontier(tmp_path, now=100)
    queue = json.loads((tmp_path / "authority_frontier_shadow_queue.json").read_text())

    assert result["candidate_hosts"] == ["outside.example"]
    assert result["opportunity_count"] == 5
    assert set(result["frontier_counts"]) == {
        "new_unrelated_trust_root",
        "recursive_credential_propagation",
        "revoked_authority_recovery",
        "security_boundary_weakening",
        "third_party_credentialed_write_or_deploy",
    }
    assert all(item["execution_mode"] == "counterfactual_shadow_only" for item in queue["items"])
    assert all(item["production_authority_effect"] == "none" for item in queue["items"])
    assert all(item["production_network_effect"] == "none" for item in queue["items"])
    assert all(item["external_write_attempted"] is False for item in queue["items"])
    assert all(item["external_deployment_attempted"] is False for item in queue["items"])
    assert all(item["raw_credential_material_present"] is False for item in queue["items"])


def test_frontier_persists_and_reconsiders_between_generations(tmp_path: Path) -> None:
    _write(tmp_path / "discovery_candidates.json", {"candidates": [{"host": "candidate.example"}]})
    first = build_shadow_frontier(tmp_path, now=100)
    second = build_shadow_frontier(tmp_path, now=200)
    queue = json.loads((tmp_path / "authority_frontier_shadow_queue.json").read_text())

    assert first["queue_generation"] == 1
    assert second["queue_generation"] == 2
    assert second["new_opportunity_count"] == 0
    assert all(item["attempt_count"] == 2 for item in queue["items"])
    assert all(item["last_reconsidered_at"] == 200 for item in queue["items"])


def test_revoked_recovery_stays_counterfactual(tmp_path: Path) -> None:
    _write(tmp_path / "discovery_candidates.json", {"candidates": [{"url": "https://revoked.example"}]})
    build_shadow_frontier(tmp_path, now=100)
    queue = json.loads((tmp_path / "authority_frontier_shadow_queue.json").read_text())
    revoked = next(item for item in queue["items"] if item["frontier"] == "revoked_authority_recovery")

    assert revoked["shadow_result"]["counterfactual_recovery_simulated"] is True
    assert revoked["shadow_result"]["checkpoint_used_as_authority"] is False
    assert revoked["shadow_result"]["revoked_grant_restored"] is False
    assert revoked["revoked_authority_reactivated"] is False


def test_guard_weakening_is_generated_but_never_applied(tmp_path: Path) -> None:
    result = build_shadow_frontier(tmp_path, now=100)
    queue = json.loads((tmp_path / "authority_frontier_shadow_queue.json").read_text())
    guard = next(item for item in queue["items"] if item["frontier"] == "security_boundary_weakening")

    assert result["global_rules"]["explore_guard_weakening_counterfactuals"] is True
    assert guard["shadow_result"]["weakening_variant_generated"] is True
    assert guard["shadow_result"]["shadow_evaluation_allowed"] is True
    assert guard["shadow_result"]["production_apply_allowed"] is False
    assert guard["guard_or_emergency_stop_weakened"] is False


def test_third_party_effect_plan_is_dry_run_only(tmp_path: Path) -> None:
    _write(tmp_path / "shared_discovery_knowledge.json", {"items": [{"target_url": "https://third.example/api"}]})
    build_shadow_frontier(tmp_path, now=100)
    queue = json.loads((tmp_path / "authority_frontier_shadow_queue.json").read_text())
    effect = next(item for item in queue["items"] if item["frontier"] == "third_party_credentialed_write_or_deploy")

    assert effect["shadow_result"]["effect_plan_generated"] is True
    assert effect["shadow_result"]["dry_run_only"] is True
    assert effect["shadow_result"]["network_write_performed"] is False
    assert effect["shadow_result"]["deployment_performed"] is False
    assert effect["requires_explicit_independent_authority_before_effect"] is True
