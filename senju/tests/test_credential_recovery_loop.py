from __future__ import annotations

from senju.authority_factory import root_from_external_scope
from senju.credential_broker import CredentialBroker, CredentialGrant
from senju.credential_recovery_loop import CredentialRecoveryLoop
from senju.credential_self_tuner import PermissionNeed
from senju.external import BUILTIN_AUTHORITY_SCOPES
from senju.secret_memory import MemorySurface, SecretMemoryIndex


def _authority():
    return root_from_external_scope(BUILTIN_AUTHORITY_SCOPES["github_metadata"], delegation_depth=4)


def _broker() -> CredentialBroker:
    broker = CredentialBroker()
    broker.register_grant(
        CredentialGrant(
            grant_id="github-a",
            provider="github",
            credential_ref="vault://github/a",
            allowed_scopes=frozenset({"metadata:read", "issues:read"}),
            required_authority_scope="public_token",
            max_ttl_seconds=300,
        )
    )
    broker.register_grant(
        CredentialGrant(
            grant_id="github-b",
            provider="github",
            credential_ref="vault://github/b",
            allowed_scopes=frozenset({"metadata:read", "issues:read"}),
            required_authority_scope="public_token",
            max_ttl_seconds=300,
        )
    )
    return broker


def _need() -> PermissionNeed:
    return PermissionNeed(
        provider="github",
        required_scopes=frozenset({"issues:read"}),
        operation="read issue metadata",
        resource="repo:test",
        ttl_seconds=60,
    )


def test_loop_tries_next_preapproved_grant_after_permission_failure() -> None:
    broker = _broker()
    loop = CredentialRecoveryLoop(broker)
    seen: list[str] = []

    def attempt(lease):
        seen.append(lease.grant_id)
        return lease.grant_id == "github-b"

    result = loop.run(_authority(), actor="META", need=_need(), attempt_operation=attempt)
    assert result.recovered is True
    assert seen == ["github-a", "github-b"]
    assert result.grant_id == "github-b"
    assert result.authority_changed is False
    assert all(broker.leases[a.lease_id].scopes == frozenset({"issues:read"}) for a in result.attempts if a.lease_id)


def test_learning_prioritises_previously_successful_grant() -> None:
    broker = _broker()
    loop = CredentialRecoveryLoop(broker)

    loop.run(
        _authority(),
        actor="META",
        need=_need(),
        attempt_operation=lambda lease: lease.grant_id == "github-b",
    )

    seen: list[str] = []
    result = loop.run(
        _authority(),
        actor="META",
        need=_need(),
        attempt_operation=lambda lease: seen.append(lease.grant_id) is None or True,
    )
    assert result.recovered is True
    assert seen[0] == "github-b"
    assert loop.learning_snapshot()["grant_successes"]["github-b"] >= 1


def test_no_matching_grant_exhausts_finite_search_space() -> None:
    broker = _broker()
    loop = CredentialRecoveryLoop(broker)
    need = PermissionNeed(
        provider="github",
        required_scopes=frozenset({"repo:write"}),
        operation="write repository",
        ttl_seconds=60,
    )
    result = loop.run(_authority(), actor="X", need=need, attempt_operation=lambda lease: True)
    assert result.recovered is False
    assert result.attempts == ()
    assert result.authority_changed is False


def test_success_is_remembered_as_opaque_pointer_only() -> None:
    broker = _broker()
    memory = SecretMemoryIndex()
    loop = CredentialRecoveryLoop(broker, secret_memory=memory)
    result = loop.run(_authority(), actor="X", need=_need(), attempt_operation=lambda lease: True)
    assert result.recovered is True

    remembered = memory.search(actor="X", surface=MemorySurface.LONG_TERM_MEMORY)
    assert len(remembered) == 1
    pointer = remembered[0]
    assert pointer.lease_id == result.lease_id
    assert pointer.resolver_key.startswith("credential-lease:")
    exported = memory.export_surface(MemorySurface.LONG_TERM_MEMORY)
    assert "vault://github/" not in str(exported)


def test_hard_attempt_cap_prevents_unbounded_retry() -> None:
    broker = _broker()
    loop = CredentialRecoveryLoop(broker, hard_attempt_cap=1)
    result = loop.run(_authority(), actor="META", need=_need(), attempt_operation=lambda lease: False)
    assert result.recovered is False
    assert len(result.attempts) == 1
