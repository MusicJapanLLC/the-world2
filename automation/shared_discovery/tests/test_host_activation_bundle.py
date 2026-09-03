from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.host_activation_bundle import (
    ATTESTATION_SCHEMA,
    BUNDLE_SCHEMA,
    HostActivationBundleError,
    action_profile,
    apply_bundle,
    check_bundle_alignment,
    load_bundle,
    validate_attestation,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(repo: Path) -> None:
    _write(repo / "AUTHORIZED_TEST_TARGETS.json", {"schema": "test", "targets": []})
    _write(
        repo / "automation/codegen/meta_state/discovery_policy.json",
        {"schema": "meta-discovery-policy/test", "action_profiles": {}},
    )


def _bundle(repo: Path, *, methods=None, paths=None) -> Path:
    methods = methods or ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"]
    paths = paths or ["/", "/test-api/synthetic"]
    path = repo / "automation/codegen/authority_bundles/new-owner.example.json"
    _write(
        path,
        {
            "schema": BUNDLE_SCHEMA,
            "authorization_id": "new-owner-001",
            "host": "new-owner.example",
            "base_url": "https://new-owner.example/",
            "authorization_request": "explicit",
            "allowed_interactions": methods,
            "owner_evidence": {
                "kind": "host_attestation",
                "url": "https://new-owner.example/.well-known/the-world-authority.json",
            },
            "senju_experimentation": {
                "enabled": True,
                "same_host_only": True,
                "synthetic_only": True,
                "trial_paths": paths,
                "allowed_methods": methods,
                "allow_method_switch": True,
                "allow_path_learning": True,
                "max_actions_per_cycle": 12,
                "payload_variants_per_route": 6,
            },
        },
    )
    return path


def _attestation(*, methods=None, prefixes=None) -> dict:
    return {
        "schema": ATTESTATION_SCHEMA,
        "host": "new-owner.example",
        "repository": "MusicJapanLLC/test",
        "authorization_id": "new-owner-001",
        "owner_authorization": "explicit",
        "allowed_interactions": methods or ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"],
        "path_prefixes": prefixes or ["/"],
        "senju_experimentation_allowed": True,
        "expires_at": 4_000_000_000,
    }


def test_one_bundle_applies_authorization_allowlist_and_senju_profile(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle_path = _bundle(repo)

    result = apply_bundle(repo, bundle_path, attestation=_attestation(), verify_live=False)
    targets = json.loads((repo / "AUTHORIZED_TEST_TARGETS.json").read_text())
    policy = json.loads((repo / "automation/codegen/meta_state/discovery_policy.json").read_text())
    target = targets["targets"][0]
    profile = policy["action_profiles"]["new-owner.example"]

    assert result["canonical_authorization_added"] is True
    assert result["authorized_target_added"] is True
    assert result["senju_trial_profile_added"] is True
    assert target["owner_authorization"] == "explicit"
    assert target["owner_authorization_evidence"]["authorization_id"] == "new-owner-001"
    assert target["follow_owner_published_external_links"] is False
    assert profile["owner_authorization"] == "explicit"
    assert set(profile["capabilities"]) == {"scan", "probe", "write", "mutation"}
    assert profile["credential_scope"] == "none"
    assert profile["senju_experimentation"]["same_host_only"] is True
    assert profile["senju_experimentation"]["synthetic_only"] is True
    assert profile["senju_experimentation"]["max_actions_per_cycle"] == 12
    assert set(profile["senju_experimentation"]["effective_trial_paths"]) == {"/", "/test-api/synthetic"}
    assert len(profile["external_actions"]["write"]) == 2
    assert len(profile["external_actions"]["mutation"]) == 4
    assert profile["authority_expansion"]["enabled"] is True
    assert profile["authority_expansion"]["max_routes_per_case"] == 6
    assert all(action["body"].find('"synthetic":true') >= 0 for rows in profile["external_actions"].values() for action in rows)

    aligned = check_bundle_alignment(repo, bundle_path)
    assert aligned["aligned"] is True
    assert aligned["canonical_authorization"] is True
    assert aligned["authorized_target"] is True
    assert aligned["senju_trial_profile"] is True


def test_new_host_bundle_cannot_apply_without_external_attestation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle_path = _bundle(repo)

    with pytest.raises(HostActivationBundleError, match="verified host attestation"):
        apply_bundle(repo, bundle_path, verify_live=False)


def test_pr_manifest_cannot_request_more_methods_than_host_attestation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle = load_bundle(_bundle(repo))

    with pytest.raises(HostActivationBundleError, match="methods not present"):
        validate_attestation(bundle, _attestation(methods=["GET", "HEAD"]))


def test_pr_manifest_cannot_expand_trial_path_beyond_attested_prefix(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle = load_bundle(_bundle(repo, paths=["/safe", "/admin/synthetic"]))

    with pytest.raises(HostActivationBundleError, match="outside attested path prefixes"):
        validate_attestation(bundle, _attestation(prefixes=["/safe"]))


def test_read_only_bundle_does_not_create_write_or_mutation_actions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle_path = _bundle(repo, methods=["GET", "HEAD", "OPTIONS"], paths=["/"])
    bundle = load_bundle(bundle_path)
    profile = action_profile(bundle)

    assert set(profile["capabilities"]) == {"scan", "probe"}
    assert profile["external_actions"] == {}
    assert profile["authority_expansion"]["enabled"] is False
    assert profile["credential_scope"] == "none"
    assert profile["senju_experimentation"]["cross_host_routes"] is False
    assert profile["senju_experimentation"]["credential_discovery"] is False


def test_bundle_alignment_fails_if_pr_only_adds_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    bundle_path = _bundle(repo)

    with pytest.raises(HostActivationBundleError, match="missing canonical explicit Authorization"):
        check_bundle_alignment(repo, bundle_path)
