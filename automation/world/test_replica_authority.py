from __future__ import annotations

import pytest

from automation.world.replica_authority import (
    ReplicaAuthorityError,
    issue_nondelegable_replica_lease,
    select_replica_profile,
)


def test_parent_effective_mode_uses_same_pre_authorized_profile() -> None:
    profile = select_replica_profile(
        parent_profile="base",
        allowed_profiles={"base", "replica-worker"},
        configured_profile="replica-worker",
        mode="parent-effective",
    )
    assert profile == "base"


def test_parent_effective_mode_cannot_escape_envelope() -> None:
    with pytest.raises(ReplicaAuthorityError, match="outside immutable envelope"):
        select_replica_profile(
            parent_profile="root-unbounded",
            allowed_profiles={"base", "replica-worker"},
            mode="parent-effective",
        )


def test_replica_lease_is_unique_and_nondelegable() -> None:
    a = issue_nondelegable_replica_lease(
        envelope_id="env-1",
        parent_worker="META",
        child_worker="child-a",
        profile="base",
    )
    b = issue_nondelegable_replica_lease(
        envelope_id="env-1",
        parent_worker="META",
        child_worker="child-b",
        profile="base",
    )
    assert a["profile"] == "base"
    assert a["delegable"] is False
    assert a["raw_credential_copied"] is False
    assert a["parent_grant_copied"] is False
    assert a["lease_id"] != b["lease_id"]
