from __future__ import annotations

import pytest

from senju.credential_delegation import (
    CredentialDelegationError,
    CredentialDelegator,
    CredentialLease,
)
from senju.link_authorization import RecursiveLinkAuthorization
from senju.trusted_scope import TrustedOwnerScope


def _scope() -> TrustedOwnerScope:
    return TrustedOwnerScope.from_dict({"domain_roots": ["example.test"]})


def test_cross_host_hop_mints_destination_bound_lease() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def issuer(source, destination, parent, scopes, ttl):
        calls.append((source, destination, None if parent is None else parent.lease_id))
        return f"lease-{destination}"

    delegator = CredentialDelegator(issuer, ttl_seconds=300)
    graph = RecursiveLinkAuthorization(_scope(), credential_delegator=delegator)
    seed_lease = CredentialLease(
        lease_id="lease-api",
        audience_host="api.example.test",
        issued_at=1.0,
        expires_at=4_000_000_000.0,
    )

    a = graph.seed("https://api.example.test/start", credential_lease=seed_lease)
    b = graph.inherit(a, "https://worker.example.test/task")

    lease = graph.credential_lease_for(b)
    assert lease is not None
    assert lease.lease_id == "lease-worker.example.test"
    assert lease.audience_host == "worker.example.test"
    assert lease.parent_lease_id == "lease-api"
    assert calls == [("api.example.test", "worker.example.test", "lease-api")]


def test_same_host_hop_reuses_lease_without_minting() -> None:
    calls = []

    def issuer(source, destination, parent, scopes, ttl):
        calls.append((source, destination))
        return "unused"

    delegator = CredentialDelegator(issuer)
    graph = RecursiveLinkAuthorization(_scope(), credential_delegator=delegator)
    seed_lease = CredentialLease(
        lease_id="lease-api",
        audience_host="api.example.test",
        issued_at=1.0,
        expires_at=4_000_000_000.0,
    )

    a = graph.seed("https://api.example.test/start", credential_lease=seed_lease)
    b = graph.inherit(a, "/next")

    assert graph.credential_lease_for(b) == seed_lease
    assert calls == []


def test_cross_host_without_delegator_drops_lease() -> None:
    graph = RecursiveLinkAuthorization(_scope())
    seed_lease = CredentialLease(
        lease_id="lease-api",
        audience_host="api.example.test",
        issued_at=1.0,
        expires_at=4_000_000_000.0,
    )

    a = graph.seed("https://api.example.test/start", credential_lease=seed_lease)
    b = graph.inherit(a, "https://worker.example.test/task")

    assert graph.credential_lease_for(b) is None


def test_lease_cannot_be_reused_for_wrong_audience() -> None:
    lease = CredentialLease(
        lease_id="lease-api",
        audience_host="api.example.test",
        issued_at=1.0,
        expires_at=4_000_000_000.0,
    )

    with pytest.raises(CredentialDelegationError, match="audience mismatch"):
        lease.validate_for("https://worker.example.test/task", now=2.0)
