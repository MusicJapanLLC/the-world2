from __future__ import annotations

import json
import time
from pathlib import Path

from engine.authorized_site_authority_accelerator import run_authorized_site_authority_accelerator
from engine.shared_discovery_authority import run_shared_discovery_authority
from senju.authority_factory import AuthorityRegistry


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_authorized_descendant_is_promoted_to_real_meta_x_senju_authority_chain(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "meta_discovery.json", {"url": "https://api.owner.example/v1"})

    discovery = run_shared_discovery_authority(state, repo_root=repo)
    assert discovery["authorized_count"] == 1

    result = run_authorized_site_authority_accelerator(state)
    assert result["promoted_count"] == 1
    row = result["promoted"][0]
    assert row["host"] == "api.owner.example"
    assert row["council"]["unanimous"] is True
    assert set(row["council"]["votes"]) == {"META", "X", "SENJU"}
    assert row["can_delegate"] is True
    assert set(row["allowed_methods"]).issubset({"GET", "HEAD", "OPTIONS"})
    assert row["credential_scope"] == "none"
    assert len(row["authority_lineage"]) == 4

    registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    final = registry.get(row["delegated_root_profile_id"])
    assert final.issuer == "Senju"
    assert final.allow_hosts == frozenset({"api.owner.example"})
    assert final.credential_scope == "none"
    assert final.allow_private_network is False
    parent_x = registry.get(final.parent_id)
    assert parent_x.issuer == "X"
    parent_meta = registry.get(parent_x.parent_id)
    assert parent_meta.issuer == "META"


def test_second_cycle_reuses_persistent_authority_instead_of_forking_lineage(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "x_external_intel.json", {"url": "https://jobs.owner.example/"})
    run_shared_discovery_authority(state, repo_root=repo)

    first = run_authorized_site_authority_accelerator(state)
    first_id = first["promoted"][0]["delegated_root_profile_id"]
    first_registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    first_count = len(first_registry.profiles)

    second = run_authorized_site_authority_accelerator(state)
    second_id = second["promoted"][0]["delegated_root_profile_id"]
    second_registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    assert second_id == first_id
    assert len(second_registry.profiles) == first_count


def test_related_candidate_is_pushed_forward_to_negotiation_but_not_minted(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["api.owner.example"]})
    _write(state / "child_discovery_log.json", {"url": "https://docs.owner.example/help"})
    discovery = run_shared_discovery_authority(state, repo_root=repo)
    assert discovery["authorized_count"] == 0

    candidates = json.loads((state / "discovery_candidates.json").read_text(encoding="utf-8"))["candidates"]
    related = [row for row in candidates if row.get("host") == "docs.owner.example"]
    assert related
    assert all(row.get("decision") == "candidate_only" for row in related)
    assert all(row.get("same_domain_hint") == "api.owner.example" for row in related)

    result = run_authorized_site_authority_accelerator(state)
    assert result["promoted_count"] == 0
    assert result["negotiation_signal_count"] >= 1

    persisted = json.loads((state / "owner_scope_negotiation_signals.json").read_text(encoding="utf-8"))["signals"]
    signals = [row for row in persisted if row.get("host") == "docs.owner.example"]
    assert len(signals) == 1
    signal = signals[0]
    assert signal["related_authorized_host"] == "api.owner.example"
    assert signal["priority"] == "high"

    registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    assert registry.profiles == {}


def test_unrelated_candidate_is_not_promoted_or_fabricated_into_negotiation_proof(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "child_discovery_log.json", {"url": "https://unrelated.example.net/"})
    run_shared_discovery_authority(state, repo_root=repo)

    result = run_authorized_site_authority_accelerator(state)
    assert result["promoted_count"] == 0
    assert result["negotiation_signal_count"] == 0
    assert result["candidate_only_minted"] is False


def test_credentialed_or_write_grant_cannot_be_upgraded_by_accelerator(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    state.mkdir(parents=True)
    now = int(time.time())
    _write(
        state / "discovery_authorized.json",
        {
            "hosts": {
                "api.owner.example": {
                    "decision": "probationary_authorized",
                    "authorization_basis": "trusted_root",
                    "authorization_reference": "owner.example",
                    "expires_at": now + 3600,
                    "allowed_methods": ["GET", "POST"],
                    "credential_scope": "service_bearer",
                    "effect": "write",
                }
            }
        },
    )

    result = run_authorized_site_authority_accelerator(state, now=now)
    assert result["promoted_count"] == 0
    assert result["rejected_count"] == 1
    assert result["rejected"][0]["council"]["unanimous"] is False
    registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    assert registry.profiles == {}


def test_promotion_bus_is_shared_with_meta_x_senju_and_sibling_agents(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    _write(state / "discovery_policy.json", {"trusted_roots": ["owner.example"]})
    _write(state / "senju_discovery.json", {"url": "https://lab.owner.example/"})
    run_shared_discovery_authority(state, repo_root=repo)
    run_authorized_site_authority_accelerator(state)

    bus = json.loads((state / "authorized_site_authority_promotion_bus.json").read_text(encoding="utf-8"))
    assert {"META", "X", "SENJU", "CLAUDE", "JULES", "OPENHANDS", "COPILOT"}.issubset(set(bus["shared_with"]))
    assert bus["promotions"][0]["operational"] is True


def test_standing_authorized_council_nomination_enters_meta_x_senju_promotion_path(tmp_path: Path) -> None:
    state = tmp_path / "meta_state"
    repo = tmp_path / "repo"
    state.mkdir(parents=True)
    repo.mkdir(parents=True)
    host = "kabeya-authorized-test-range.onrender.com"
    reference = "canonical:kabeya-authorized-test-range"

    _write(
        repo / "senju" / "state" / "standing_authorizations.json",
        {
            "schema": "senju-standing-authorization/v1",
            "records": [
                {
                    "authorization_reference": reference,
                    "owner": "MusicJapanLLC",
                    "issuer_kind": "canonical_repository",
                    "exact_hosts": [host],
                    "allowed_methods": ["GET", "HEAD", "OPTIONS"],
                    "created_at_utc": "2026-08-31T07:18:46+00:00",
                    "revoked": False,
                    "credential_scope": "none",
                    "destructive": False,
                }
            ],
        },
    )
    _write(
        state / "council_discovery_nomination.json",
        {
            "schema": "meta-authority-council-discovery-nomination/v1",
            "nomination": {
                "host": host,
                "url": f"https://{host}/",
                "authorization_reference": reference,
                "requested_council": ["META", "X", "SENJU"],
                "recommendation": "approval_permitted_and_recommended_after_independent_council_checks",
            },
        },
    )

    discovery = run_shared_discovery_authority(state, repo_root=repo)
    assert discovery["authorized_count"] == 1
    grant = json.loads((state / "discovery_authorized.json").read_text(encoding="utf-8"))["hosts"][host]
    assert grant["authorization_basis"] == "standing_authorization_exact_host"
    assert grant["credential_scope"] == "none"

    result = run_authorized_site_authority_accelerator(state)
    assert result["promoted_count"] == 1
    row = result["promoted"][0]
    assert row["host"] == host
    assert row["authorization_reference"] == host
    assert row["council"]["unanimous"] is True
    assert all(row["council"]["votes"][actor]["approved"] for actor in ("META", "X", "SENJU"))
    assert row["credential_scope"] == "none"
    assert set(row["allowed_methods"]).issubset({"GET", "HEAD", "OPTIONS"})

    registry = AuthorityRegistry.load(state / "authorized_site_authority_registry.json")
    leaf = registry.get(row["delegated_root_profile_id"])
    assert leaf.issuer == "Senju"
    assert leaf.allow_hosts == frozenset({host})
    assert leaf.can_delegate is True
