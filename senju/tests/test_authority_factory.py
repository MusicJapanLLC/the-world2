from __future__ import annotations

import json

import pytest

from senju.authority_factory import (
    AuthorityMintError,
    AuthorityMintRequest,
    AuthorityRegistry,
    mint_child,
    root_from_external_scope,
)
from senju.external import BUILTIN_AUTHORITY_SCOPES


def _root(name: str = "threat_intel_public", depth: int = 4):
    return root_from_external_scope(BUILTIN_AUTHORITY_SCOPES[name], delegation_depth=depth)


def test_meta_can_mint_child_and_x_can_mint_grandchild() -> None:
    root = _root(depth=4)
    child = mint_child(
        root,
        AuthorityMintRequest(
            purpose="META NVD research",
            allow_hosts=frozenset({"services.nvd.nist.gov"}),
            allowed_methods=frozenset({"GET", "HEAD"}),
            rate_limit_per_minute=10,
            can_delegate=True,
        ),
        issuer="META",
    )
    grandchild = mint_child(
        child,
        AuthorityMintRequest(
            purpose="X HEAD-only verification",
            allowed_methods=frozenset({"HEAD"}),
            rate_limit_per_minute=4,
            can_delegate=True,
        ),
        issuer="X",
    )

    assert child.parent_id == root.profile_id
    assert grandchild.parent_id == child.profile_id
    assert grandchild.generation == 2
    assert grandchild.allow_hosts == frozenset({"services.nvd.nist.gov"})
    assert grandchild.allowed_methods == frozenset({"HEAD"})
    assert grandchild.rate_limit_per_minute == 4
    assert grandchild.delegation_depth_remaining == 2


def test_senju_can_mint_equally_scoped_child_but_depth_always_decreases() -> None:
    root = _root(depth=2)
    child = mint_child(root, AuthorityMintRequest(purpose="same scope", can_delegate=True), issuer="Senju")
    assert child.allow_hosts == root.allow_hosts
    assert child.allowed_methods == root.allowed_methods
    assert child.delegation_depth_remaining == 1

    grandchild = mint_child(child, AuthorityMintRequest(purpose="terminal child", can_delegate=True), issuer="META")
    assert grandchild.delegation_depth_remaining == 0
    assert grandchild.can_delegate is False

    with pytest.raises(AuthorityMintError):
        mint_child(grandchild, AuthorityMintRequest(purpose="too deep"), issuer="X")


def test_cannot_add_host_not_in_parent() -> None:
    root = _root()
    with pytest.raises(AuthorityMintError, match="cannot add hosts"):
        mint_child(
            root,
            AuthorityMintRequest(
                purpose="bad host expansion",
                allow_hosts=frozenset(set(root.allow_hosts) | {"unapproved.example"}),
            ),
            issuer="META",
        )


def test_cannot_add_method_not_in_parent() -> None:
    root = _root()
    assert "DELETE" not in root.allowed_methods
    with pytest.raises(AuthorityMintError, match="cannot add methods"):
        mint_child(
            root,
            AuthorityMintRequest(purpose="bad method expansion", allowed_methods=frozenset({"GET", "DELETE"})),
            issuer="X",
        )


def test_cannot_increase_credential_scope() -> None:
    root = _root("threat_intel_public")
    assert root.credential_scope == "none"
    with pytest.raises(AuthorityMintError, match="cannot increase credential"):
        mint_child(
            root,
            AuthorityMintRequest(purpose="bad credential expansion", credential_scope="service_bearer"),
            issuer="Senju",
        )


def test_cannot_create_private_network_authority_from_public_parent() -> None:
    root = _root()
    assert root.allow_private_network is False
    with pytest.raises(AuthorityMintError, match="cannot create private-network authority"):
        mint_child(
            root,
            AuthorityMintRequest(
                purpose="bad private expansion",
                allow_private_network=True,
                private_hosts=frozenset({"internal.example"}),
                private_cidrs=("10.0.0.0/8",),
            ),
            issuer="META",
        )


def test_untrusted_issuer_cannot_mint() -> None:
    root = _root()
    with pytest.raises(AuthorityMintError, match="issuer is not allowed"):
        mint_child(root, AuthorityMintRequest(purpose="unknown agent"), issuer="RandomBot")


def test_registry_seeds_fixed_roots_and_persists_recursive_chain(tmp_path) -> None:
    path = tmp_path / "authorities.json"
    registry = AuthorityRegistry(path)
    registry.seed_builtin_roots(delegation_depth=3)
    parent_id = "root:threat_intel_public"
    child = registry.mint(
        parent_id,
        AuthorityMintRequest(
            purpose="META narrowed feed",
            allow_hosts=frozenset({"services.nvd.nist.gov"}),
            allowed_methods=frozenset({"GET"}),
            can_delegate=True,
        ),
        issuer="META",
    )
    grandchild = registry.mint(
        child.profile_id,
        AuthorityMintRequest(purpose="Senju inherited feed", can_delegate=False),
        issuer="Senju",
    )
    registry.save()

    restored = AuthorityRegistry.load(path)
    assert restored.get(child.profile_id).fingerprint == child.fingerprint
    assert restored.get(grandchild.profile_id).parent_id == child.profile_id


def test_registry_detects_profile_tampering(tmp_path) -> None:
    path = tmp_path / "authorities.json"
    registry = AuthorityRegistry(path)
    registry.seed_builtin_roots(delegation_depth=3)
    registry.save()

    data = json.loads(path.read_text())
    data["profiles"][0]["rate_limit_per_minute"] += 999
    path.write_text(json.dumps(data))

    with pytest.raises(AuthorityMintError, match="fingerprint mismatch"):
        AuthorityRegistry.load(path)
