from __future__ import annotations

from pathlib import Path

import validate_host_activation_pr as validator


def _target_doc(*hosts: str) -> dict:
    return {"targets": [{"host": host, "owner_authorization": "explicit"} for host in hosts]}


def _policy_doc(*hosts: str) -> dict:
    return {"action_profiles": {host: {"owner_authorization": "explicit"} for host in hosts}}


def _bundle(host: str, *, enabled: bool = True, learning: bool = True) -> dict:
    return {
        "host": host,
        "senju_experimentation": {
            "enabled": enabled,
            "same_host_only": True,
            "synthetic_only": True,
            "allowed_methods": ["GET", "HEAD"],
            "trial_paths": ["/", "/health"],
            "max_actions_per_cycle": 6,
            "payload_variants_per_route": 1,
            "allow_path_learning": learning,
            "allow_method_switch": False,
        },
    }


def _wire(monkeypatch, tmp_path: Path, *, base_targets=(), head_targets=(), base_profiles=(), head_profiles=(), bundles=None):
    bundle_map = bundles or {}
    fake_paths = [tmp_path / f"{host}.json" for host in bundle_map]
    path_to_host = {str(path): host for path, host in zip(fake_paths, bundle_map)}

    def fake_json_at(ref: str, path: str):
        if path == validator.TARGETS_PATH:
            return _target_doc(*(base_targets if ref == "base" else head_targets))
        if path == validator.POLICY_PATH:
            return _policy_doc(*(base_profiles if ref == "base" else head_profiles))
        return {}

    monkeypatch.setattr(validator, "_json_at", fake_json_at)
    monkeypatch.setattr(validator, "_changed_bundle_paths", lambda base, head, repo_root: fake_paths)
    monkeypatch.setattr(validator, "load_bundle", lambda path: bundle_map[path_to_host[str(path)]])
    monkeypatch.setattr(
        validator,
        "check_bundle_alignment",
        lambda root, path: {
            "host": path_to_host[str(path)],
            "aligned": True,
            "canonical_authorization": True,
            "authorized_target": True,
            "senju_trial_profile": True,
        },
    )


def test_target_only_pr_is_advisory_not_rejected(monkeypatch, tmp_path: Path) -> None:
    _wire(monkeypatch, tmp_path, head_targets=("new.example",), head_profiles=(), bundles={})
    result = validator.validate_pr("base", "head", repo_root=tmp_path)
    assert result["blocking"] is False
    assert result["partial_new_host_pr_allowed"] is True
    assert result["progression"]["new.example"]["stage"] == "authorized_target_only"


def test_candidate_bundle_without_authorization_is_allowed(monkeypatch, tmp_path: Path) -> None:
    _wire(monkeypatch, tmp_path, bundles={"new.example": _bundle("new.example")})
    result = validator.validate_pr("base", "head", repo_root=tmp_path)
    assert result["blocking"] is False
    assert result["candidate_only_pr_allowed"] is True
    assert result["progression"]["new.example"]["stage"] == "candidate_bundle"


def test_profile_can_follow_authorization_later(monkeypatch, tmp_path: Path) -> None:
    _wire(monkeypatch, tmp_path, head_targets=("new.example",), head_profiles=("new.example",), bundles={})
    result = validator.validate_pr("base", "head", repo_root=tmp_path)
    assert result["profile_can_follow_later"] is True
    assert result["progression"]["new.example"]["stage"] == "authorized_profiled"


def test_complete_host_reports_senju_ready(monkeypatch, tmp_path: Path) -> None:
    _wire(
        monkeypatch,
        tmp_path,
        head_targets=("new.example",),
        head_profiles=("new.example",),
        bundles={"new.example": _bundle("new.example")},
    )
    result = validator.validate_pr("base", "head", repo_root=tmp_path)
    assert result["progression"]["new.example"]["stage"] == "senju_trial_ready"
    assert result["progression"]["new.example"]["senju_trial_ready"] is True
