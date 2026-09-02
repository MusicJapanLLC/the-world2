from __future__ import annotations

import dataclasses

import pytest

from senju.authority_factory import root_from_external_scope
from senju.credential_broker import (
    CredentialBroker,
    CredentialBrokerError,
    CredentialGrant,
)
from senju.external import BUILTIN_AUTHORITY_SCOPES


def _authority(name: str = "github_metadata"):
    return root_from_external_scope(BUILTIN_AUTHORITY_SCOPES[name], delegation_depth=4)


def _broker() -> CredentialBroker:
    broker = CredentialBroker()
    broker.register_grant(
        CredentialGrant(
            grant_id="github-readonly",
            provider="github",
            credential_ref="vault://senju/github-readonly",
            allowed_scopes=frozenset({"repo:read", "issues:read", "metadata:read"}),
            required_authority_scope="public_token",
            max_ttl_seconds=900,
            exchangeable=True,
            delegable=True,
            description="Read-only GitHub metadata grant",
        )
    )
    return broker


def test_meta_can_discover_only_preapproved_grant_metadata() -> None:
    broker = _broker()
    catalog = broker.discover("META")
    assert catalog[0]["grant_id"] == "github-readonly"
    assert "credential_ref" not in catalog[0]


def test_meta_can_issue_and_exchange_to_narrower_scope() -> None:
    broker = _broker()
    authority = _authority()
    lease = broker.issue(
        authority,
        actor="META",
        grant_id="github-readonly",
        scopes={"repo:read", "issues:read"},
        ttl_seconds=300,
    )
    child = broker.exchange(
        authority,
        actor="META",
        parent_lease_id=lease.lease_id,
        scopes={"issues:read"},
        ttl_seconds=60,
    )
    assert child.parent_lease_id == lease.lease_id
    assert child.scopes == frozenset({"issues:read"})
    assert child.generation == 1


def test_meta_can_delegate_narrower_lease_to_x() -> None:
    broker = _broker()
    authority = _authority()
    lease = broker.issue(
        authority,
        actor="META",
        grant_id="github-readonly",
        scopes={"repo:read", "metadata:read"},
        ttl_seconds=300,
    )
    delegated = broker.delegate(
        authority,
        actor="META",
        recipient="X",
        parent_lease_id=lease.lease_id,
        scopes={"metadata:read"},
        ttl_seconds=60,
    )
    assert delegated.actor == "X"
    assert broker.resolve_credential_ref(actor="X", lease_id=delegated.lease_id) == "vault://senju/github-readonly"
    with pytest.raises(CredentialBrokerError, match="does not own"):
        broker.resolve_credential_ref(actor="META", lease_id=delegated.lease_id)


def test_scope_expansion_is_rejected() -> None:
    broker = _broker()
    authority = _authority()
    with pytest.raises(CredentialBrokerError, match="cannot expand"):
        broker.issue(
            authority,
            actor="X",
            grant_id="github-readonly",
            scopes={"repo:read", "repo:write"},
            ttl_seconds=120,
        )


def test_exchange_cannot_recover_scope_removed_by_parent() -> None:
    broker = _broker()
    authority = _authority()
    lease = broker.issue(
        authority,
        actor="META",
        grant_id="github-readonly",
        scopes={"metadata:read"},
        ttl_seconds=300,
    )
    with pytest.raises(CredentialBrokerError, match="cannot expand"):
        broker.exchange(
            authority,
            actor="META",
            parent_lease_id=lease.lease_id,
            scopes={"metadata:read", "repo:read"},
            ttl_seconds=60,
        )


def test_public_authority_without_credential_scope_cannot_issue() -> None:
    broker = _broker()
    authority = _authority("threat_intel_public")
    assert authority.credential_scope == "none"
    with pytest.raises(CredentialBrokerError, match="lacks required credential authority"):
        broker.issue(
            authority,
            actor="META",
            grant_id="github-readonly",
            scopes={"metadata:read"},
            ttl_seconds=60,
        )


def test_unknown_grant_is_not_discovered_or_acquired() -> None:
    broker = _broker()
    authority = _authority()
    with pytest.raises(CredentialBrokerError, match="not pre-approved"):
        broker.issue(
            authority,
            actor="META",
            grant_id="found-in-random-file",
            scopes={"metadata:read"},
            ttl_seconds=60,
        )


def test_admin_or_root_scopes_cannot_be_registered_for_autonomous_brokering() -> None:
    for scope in ("admin", "administrator", "root", "repo/admin", "full_access", "*"):
        with pytest.raises(CredentialBrokerError, match="administrator/root"):
            CredentialGrant(
                grant_id=f"bad-{scope}",
                provider="example",
                credential_ref="vault://bad",
                allowed_scopes=frozenset({scope}),
                required_authority_scope="public_token",
            )


def test_untrusted_actor_cannot_use_broker() -> None:
    broker = _broker()
    with pytest.raises(CredentialBrokerError, match="not allowed"):
        broker.discover("RandomBot")


def test_revoked_and_tampered_leases_fail_closed() -> None:
    broker = _broker()
    authority = _authority()
    lease = broker.issue(
        authority,
        actor="X",
        grant_id="github-readonly",
        scopes={"metadata:read"},
        ttl_seconds=120,
    )
    broker.revoke(actor="X", lease_id=lease.lease_id)
    with pytest.raises(CredentialBrokerError, match="revoked"):
        broker.resolve_credential_ref(actor="X", lease_id=lease.lease_id)

    second = broker.issue(
        authority,
        actor="X",
        grant_id="github-readonly",
        scopes={"metadata:read"},
        ttl_seconds=120,
    )
    broker.leases[second.lease_id] = dataclasses.replace(second, scopes=frozenset({"repo:write"}))
    with pytest.raises(CredentialBrokerError, match="fingerprint mismatch"):
        broker.resolve_credential_ref(actor="X", lease_id=second.lease_id)
