from __future__ import annotations

from senju.authority_factory import root_from_external_scope
from senju.credential_broker import CredentialBroker, CredentialGrant
from senju.credential_self_tuner import (
    CredentialSelfTuner,
    PermissionNeed,
    TuneOutcome,
    TuneStrategy,
)
from senju.external import BUILTIN_AUTHORITY_SCOPES
from senju.secret_memory import MemorySurface, SecretMemoryIndex


def _authority(name: str = "github_metadata"):
    return root_from_external_scope(BUILTIN_AUTHORITY_SCOPES[name], delegation_depth=4)


def _broker() -> CredentialBroker:
    broker = CredentialBroker()
    broker.register_grant(
        CredentialGrant(
            grant_id="github-broad-read",
            provider="github",
            credential_ref="vault://senju/github-broad-read",
            allowed_scopes=frozenset({"repo:read", "issues:read", "metadata:read"}),
            required_authority_scope="public_token",
            max_ttl_seconds=900,
        )
    )
    broker.register_grant(
        CredentialGrant(
            grant_id="github-repo-read",
            provider="github",
            credential_ref="vault://senju/github-repo-read",
            allowed_scopes=frozenset({"repo:read"}),
            required_authority_scope="public_token",
            max_ttl_seconds=300,
        )
    )
    return broker


def test_permission_failure_selects_smallest_preapproved_grant() -> None:
    broker = _broker()
    authority = _authority()
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="META",
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"repo:read"}),
            operation="read_repository",
        ),
    )

    assert result.outcome is TuneOutcome.RECOVERED
    assert result.strategy is TuneStrategy.PREAPPROVED_GRANT_SWITCH
    assert result.grant_id == "github-repo-read"
    assert result.authority_changed is False
    assert result.raw_secret_exposed is False
    lease = broker.leases[result.lease_id]
    assert lease.scopes == frozenset({"repo:read"})


def test_broader_current_lease_is_attenuated_by_exchange() -> None:
    broker = _broker()
    authority = _authority()
    current = broker.issue(
        authority,
        actor="X",
        grant_id="github-broad-read",
        scopes={"repo:read", "issues:read"},
        ttl_seconds=300,
    )
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="X",
        current_lease_id=current.lease_id,
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"issues:read"}),
            operation="read_issue",
            ttl_seconds=60,
        ),
    )

    assert result.outcome is TuneOutcome.RECOVERED
    assert result.strategy is TuneStrategy.NARROW_EXCHANGE
    child = broker.leases[result.lease_id]
    assert child.parent_lease_id == current.lease_id
    assert child.scopes == frozenset({"issues:read"})


def test_permission_failure_can_switch_within_preapproved_ceiling_not_expand_authority() -> None:
    broker = _broker()
    authority = _authority()
    current = broker.issue(
        authority,
        actor="META",
        grant_id="github-broad-read",
        scopes={"metadata:read"},
        ttl_seconds=300,
    )
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="META",
        current_lease_id=current.lease_id,
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"repo:read"}),
            operation="read_repository",
        ),
    )

    assert result.outcome is TuneOutcome.RECOVERED
    assert result.strategy is TuneStrategy.PREAPPROVED_GRANT_SWITCH
    assert result.authority_credential_scope == authority.credential_scope
    assert result.authority_changed is False
    assert broker.leases[result.lease_id].scopes == frozenset({"repo:read"})


def test_unknown_scope_requests_approval_instead_of_registering_or_widening_grants() -> None:
    broker = _broker()
    authority = _authority()
    before_grants = set(broker.grants)
    before_leases = set(broker.leases)
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="META",
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"repo:write"}),
            operation="write_repository",
        ),
    )

    assert result.outcome is TuneOutcome.APPROVAL_REQUIRED
    assert result.strategy is TuneStrategy.REQUEST_PREAPPROVED_GRANT
    assert set(broker.grants) == before_grants
    assert set(broker.leases) == before_leases
    assert result.authority_changed is False


def test_insufficient_authority_does_not_self_escalate() -> None:
    broker = _broker()
    authority = _authority("threat_intel_public")
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="X",
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"repo:read"}),
            operation="read_repository",
        ),
    )

    assert authority.credential_scope == "none"
    assert result.outcome is TuneOutcome.APPROVAL_REQUIRED
    assert result.authority_changed is False
    assert not broker.leases


def test_privileged_scope_is_denied_before_broker_mutation() -> None:
    broker = _broker()
    authority = _authority()
    tuner = CredentialSelfTuner(broker)

    result = tuner.recover_permission_failure(
        authority,
        actor="META",
        need=PermissionNeed(
            provider="github",
            required_scopes=frozenset({"repo/admin"}),
            operation="change_repository_admin",
        ),
    )

    assert result.outcome is TuneOutcome.DENIED
    assert result.strategy is TuneStrategy.DENY_PRIVILEGED_SCOPE
    assert not broker.leases


def test_success_is_learned_and_secret_memory_contains_only_pointer_metadata() -> None:
    broker = _broker()
    authority = _authority()
    memory = SecretMemoryIndex()
    tuner = CredentialSelfTuner(broker, secret_memory=memory)
    need = PermissionNeed(
        provider="github",
        required_scopes=frozenset({"repo:read"}),
        operation="read_repository",
    )

    first = tuner.recover_permission_failure(authority, actor="META", need=need)
    second = tuner.recover_permission_failure(authority, actor="META", need=need)

    assert first.recovered and second.recovered
    assert tuner.strategy_score(TuneStrategy.PREAPPROVED_GRANT_SWITCH) == 2
    history = tuner.history()
    assert all(event["reward"] == 1.0 for event in history)
    assert all("credential_ref" not in event for event in history)

    records = memory.export_surface(MemorySurface.LONG_TERM_MEMORY)
    assert len(records) == 2
    assert all(record["provider"] == "github" for record in records)
    assert all("credential_ref" not in record for record in records)
    assert all(record["resolver_key"].startswith("credential-lease:") for record in records)
