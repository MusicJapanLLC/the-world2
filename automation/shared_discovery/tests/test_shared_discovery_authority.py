from __future__ import annotations

import json
from pathlib import Path

from engine.shared_discovery_authority import run_shared_discovery_authority


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_meta_x_child_discoveries_share_and_promote_inside_owner_root(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {"trusted_roots": ["owner.example"], "company_domains": []},
    )
    _write(state / "meta_discovery.json", {"url": "https://api.owner.example/v1"})
    _write(state / "x_external_intel.json", {"links": ["https://docs.owner.example/help"]})
    _write(state / "children" / "child-7-crawler.json", {"href": "https://lab.owner.example/a"})

    result = run_shared_discovery_authority(state, repo_root=repo)

    assert result["shared_discovery_count"] == 3
    assert result["authorized_count"] == 3
    assert result["action_ready_count"] == 3

    shared = json.loads((state / "shared_discovery_knowledge.json").read_text())
    actors = {actor for row in shared["discoveries"] for actor in row["actors"]}
    assert {"META", "X", "CHILD"}.issubset(actors)
    assert {"META", "X", "SENJU", "CHILD", "AI"} == set(shared["global_knowledge_consumers"])
    assert all(row["interesting"] is True for row in shared["discoveries"])
    assert all(row["decision"] == "probationary_authorized" for row in shared["discoveries"])

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    assert len(queue["actions"]) == 3
    assert all(set(row["capabilities"]) == {"scan", "probe"} for row in queue["actions"])
    assert all(row["credential_scope"] == "none" for row in queue["actions"])
    assert all(set(row["shared_with"]) == {"META", "X", "SENJU", "CHILD", "AI"} for row in queue["actions"])


def test_unrelated_discovery_is_shared_but_never_auto_authorized(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(
        state / "child_discovery_log.json",
        {"interesting": True, "url": "https://unrelated-third-party.example/path"},
    )

    result = run_shared_discovery_authority(state, repo_root=repo)

    assert result["shared_discovery_count"] == 1
    assert result["authorized_count"] == 0
    assert result["action_ready_count"] == 0

    shared = json.loads((state / "shared_discovery_knowledge.json").read_text())
    assert shared["discoveries"][0]["decision"] == "candidate_only"
    queue = json.loads((state / "discovery_action_queue.json").read_text())
    assert queue["actions"] == []


def test_exact_explicit_profile_can_add_write_mutation_and_credentialed_capability(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": ["owner.example"],
            "action_profiles": {
                "api.owner.example": {
                    "owner_authorization": "explicit",
                    "capabilities": ["scan", "probe", "write", "mutation", "credentialed_action"],
                    "credential_scope": "owner-api-service",
                }
            },
        },
    )
    _write(state / "meta_discovery.json", {"url": "https://api.owner.example/v2/resource"})

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["authorized_count"] == 1
    assert result["high_impact_ready_count"] == 1
    assert result["inherited_high_impact_ready_count"] == 0

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    action = queue["actions"][0]
    assert set(action["capabilities"]) == {
        "scan",
        "probe",
        "write",
        "mutation",
        "credentialed_action",
    }
    assert action["credential_scope"] == "owner-api-service"
    assert action["capability_authorization_profile"] == "api.owner.example"
    assert action["capability_inherited_from_owner_root"] is False


def test_high_impact_profile_does_not_inherit_without_explicit_inheritance_flag(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": ["owner.example"],
            "action_profiles": {
                "owner.example": {
                    "owner_authorization": "explicit",
                    "capabilities": ["write", "mutation", "credentialed_action"],
                    "credential_scope": "root-secret",
                }
            },
        },
    )
    _write(state / "x_discovery.json", {"url": "https://new.owner.example/"})

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["authorized_count"] == 1
    assert result["high_impact_ready_count"] == 0

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    action = queue["actions"][0]
    assert set(action["capabilities"]) == {"scan", "probe"}
    assert action["credential_scope"] == "none"
    assert action["capability_inherited_from_owner_root"] is False


def test_explicit_owner_root_profile_auto_inherits_high_impact_to_discovered_descendants(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": ["owner.example"],
            "action_profiles": {
                "owner.example": {
                    "owner_authorization": "explicit",
                    "inherit_to_descendants": True,
                    "capabilities": ["write", "mutation", "credentialed_action"],
                    "credential_scope": "owner-root-service",
                }
            },
        },
    )
    _write(state / "meta_discovery.json", {"url": "https://api.owner.example/v3"})
    _write(state / "x_external_intel.json", {"url": "https://jobs.owner.example/admin"})
    _write(state / "children" / "child-crawler.json", {"url": "https://lab.owner.example/test"})

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["authorized_count"] == 3
    assert result["high_impact_ready_count"] == 3
    assert result["inherited_high_impact_ready_count"] == 3

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    assert len(queue["actions"]) == 3
    for action in queue["actions"]:
        assert set(action["capabilities"]) == {
            "scan",
            "probe",
            "write",
            "mutation",
            "credentialed_action",
        }
        assert action["credential_scope"] == "owner-root-service"
        assert action["capability_authorization_profile"] == "owner.example"
        assert action["capability_inherited_from_owner_root"] is True


def test_exact_profile_can_narrow_an_inherited_owner_root_profile(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": ["owner.example"],
            "action_profiles": {
                "owner.example": {
                    "owner_authorization": "explicit",
                    "inherit_to_descendants": True,
                    "capabilities": ["write", "mutation", "credentialed_action"],
                    "credential_scope": "root-scope",
                },
                "readonly.owner.example": {
                    "owner_authorization": "explicit",
                    "capabilities": ["scan", "probe"],
                    "credential_scope": "none",
                },
            },
        },
    )
    _write(state / "meta_discovery.json", {"url": "https://readonly.owner.example/report"})

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["authorized_count"] == 1
    assert result["high_impact_ready_count"] == 0

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    action = queue["actions"][0]
    assert set(action["capabilities"]) == {"scan", "probe"}
    assert action["credential_scope"] == "none"
    assert action["capability_authorization_profile"] == "readonly.owner.example"
    assert action["capability_inherited_from_owner_root"] is False


def test_inherited_credentialed_action_requires_named_existing_credential_scope(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(
        state / "discovery_policy.json",
        {
            "trusted_roots": ["owner.example"],
            "action_profiles": {
                "owner.example": {
                    "owner_authorization": "explicit",
                    "inherit_to_descendants": True,
                    "capabilities": ["write", "credentialed_action"],
                    "credential_scope": "none",
                }
            },
        },
    )
    _write(state / "child_discovery_log.json", {"url": "https://new.owner.example/"})

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["authorized_count"] == 1
    assert result["high_impact_ready_count"] == 1

    queue = json.loads((state / "discovery_action_queue.json").read_text())
    action = queue["actions"][0]
    assert set(action["capabilities"]) == {"scan", "probe", "write"}
    assert action["credential_scope"] == "none"


def test_generated_discovery_outputs_do_not_feed_themselves(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)

    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "meta_discovery.json", {"url": "https://a.owner.example/"})
    _write(
        state / "discovery_candidates.json",
        {"candidates": [{"url": "https://should-not-be-reingested.owner.example/"}]},
    )

    result = run_shared_discovery_authority(state, repo_root=repo)
    assert result["shared_discovery_count"] == 1
