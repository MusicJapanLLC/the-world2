from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.production_state_bootstrap import (
    ProductionStateBootstrapError,
    bootstrap_owner_runtime_state,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _owner_config(repo: Path) -> Path:
    source = repo / "automation" / "codegen" / "meta_state"
    _write(
        source / "discovery_policy.json",
        {
            "schema": "test-policy/v1",
            "trusted_roots": ["owner.example"],
            "authorization_rule": {"inside_existing_owner_envelope": "discovered == authorized"},
        },
    )
    _write(
        source / "meta_discovery_seed.json",
        {
            "schema": "test-seed/v1",
            "interesting": True,
            "url": "https://owner.example/",
        },
    )
    _write(source / "network_policy_envelope.json", {"schema": "network/v1", "roots": ["owner.example"]})
    return source


def test_bootstrap_overwrites_stale_runtime_owner_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "runtime"
    _owner_config(repo)
    _write(
        state / "discovery_policy.json",
        {"schema": "stale-runtime", "trusted_roots": ["stale.invalid"]},
    )

    receipt = bootstrap_owner_runtime_state(state, repo_root=repo, now=1234)

    runtime_policy = json.loads((state / "discovery_policy.json").read_text())
    runtime_seed = json.loads((state / "meta_discovery_seed.json").read_text())
    assert runtime_policy["trusted_roots"] == ["owner.example"]
    assert runtime_seed["interesting"] is True
    assert receipt["authority_source"] == "trusted_production_checkout"
    assert receipt["required_files_present"] is True
    assert receipt["runtime_cache_may_override_owner_policy"] is False
    assert receipt["stale_runtime_policy_replaced"] is True
    assert receipt["generated_authority_imported"] is False
    assert {row["name"] for row in receipt["copied_files"]}.issuperset(
        {"discovery_policy.json", "meta_discovery_seed.json"}
    )

    stored = json.loads((state / "owner_runtime_bootstrap.json").read_text())
    assert stored == receipt


def test_bootstrap_does_not_import_generated_authority_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    state = tmp_path / "runtime"
    source = _owner_config(repo)
    _write(source / "discovery_authorized.json", {"hosts": {"should-not-import.example": {}}})
    _write(source / "discovery_capability_leases.json", {"leases": [{"target": "should-not-import.example"}]})
    _write(source / "discovery_action_queue.json", {"actions": [{"target": "should-not-import.example"}]})

    receipt = bootstrap_owner_runtime_state(state, repo_root=repo)

    assert not (state / "discovery_authorized.json").exists()
    assert not (state / "discovery_capability_leases.json").exists()
    assert not (state / "discovery_action_queue.json").exists()
    assert receipt["generated_authority_imported"] is False


def test_bootstrap_requires_discovery_policy_and_seed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "automation" / "codegen" / "meta_state"
    _write(source / "discovery_policy.json", {"schema": "only-policy"})

    with pytest.raises(ProductionStateBootstrapError, match="required owner runtime config missing"):
        bootstrap_owner_runtime_state(tmp_path / "runtime", repo_root=repo)


def test_invalid_required_owner_config_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "automation" / "codegen" / "meta_state"
    source.mkdir(parents=True)
    (source / "discovery_policy.json").write_text("[]", encoding="utf-8")
    _write(source / "meta_discovery_seed.json", {"interesting": True, "url": "https://owner.example/"})

    with pytest.raises(ProductionStateBootstrapError, match="must be an object"):
        bootstrap_owner_runtime_state(tmp_path / "runtime", repo_root=repo)
