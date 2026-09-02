from __future__ import annotations

import pytest

from senju.credential_broker import CredentialLease
from senju.secret_memory import (
    MemorySurface,
    SecretMemoryError,
    SecretMemoryIndex,
    assert_no_raw_secret_fields,
)


def test_secret_pointer_can_be_persisted_to_every_supported_surface() -> None:
    index = SecretMemoryIndex()
    pointer = index.remember(
        resolver_key="credential-lease:cred:meta:123",
        owner_actor="META",
        provider="github",
        purpose="repository automation",
        surfaces=list(MemorySurface),
        scopes=["repo:status", "pull_request:write"],
        expires_at_utc="2026-08-31T07:00:00+00:00",
        rotation_generation=2,
        grant_id="grant:github-meta",
        lease_id="cred:meta:123",
        tags=["automation", "github"],
    )

    assert pointer.owner_actor == "META"
    for surface in MemorySurface:
        exported = index.export_surface(surface)
        assert len(exported) == 1
        assert exported[0]["pointer_id"] == pointer.pointer_id
        assert exported[0]["lease_id"] == "cred:meta:123"
        assert exported[0]["rotation_generation"] == 2


def test_credential_lease_memory_never_persists_credential_ref() -> None:
    lease = CredentialLease(
        lease_id="cred:x:abc",
        grant_id="grant:test",
        actor="X",
        credential_ref="vault://do-not-persist/raw-reference",
        scopes=frozenset({"read", "write"}),
        issued_at_utc="2026-08-31T06:00:00+00:00",
        expires_at_utc="2026-08-31T06:10:00+00:00",
        generation=3,
        parent_lease_id="cred:meta:parent",
        fingerprint="fingerprint-not-used-by-memory-test",
    )
    index = SecretMemoryIndex()
    pointer = index.remember_credential_lease(
        lease,
        provider="internal-api",
        purpose="bounded automation",
        surfaces=[MemorySurface.LONG_TERM_MEMORY, MemorySurface.SLACK, MemorySurface.GITHUB_PR_BODY],
        tags=["credential", "runtime"],
    )

    assert pointer.resolver_key == "credential-lease:cred:x:abc"
    exported = index.export_all()
    text = repr(exported)
    assert "vault://do-not-persist/raw-reference" not in text
    assert "credential_ref" not in text
    assert "cred:x:abc" in text


def test_rotation_creates_new_generation_and_parent_link() -> None:
    index = SecretMemoryIndex()
    first = index.remember(
        resolver_key="credential-lease:cred:meta:v1",
        owner_actor="META",
        provider="slack",
        purpose="notification",
        surfaces=[MemorySurface.LONG_TERM_MEMORY, MemorySurface.HYPOTHESIS_TRACKER],
        scopes=["chat:write"],
        rotation_generation=0,
        lease_id="cred:meta:v1",
    )
    second = index.rotate(
        first.pointer_id,
        resolver_key="credential-lease:cred:meta:v2",
        expires_at_utc="2026-08-31T08:00:00+00:00",
        lease_id="cred:meta:v2",
    )

    assert second.rotation_generation == 1
    assert second.parent_pointer_id == first.pointer_id
    assert second.scopes == first.scopes
    assert set(index.surfaces[MemorySurface.LONG_TERM_MEMORY]) == {first.pointer_id, second.pointer_id}


def test_search_supports_actor_provider_tag_and_surface() -> None:
    index = SecretMemoryIndex()
    meta = index.remember(
        resolver_key="credential-lease:meta",
        owner_actor="META",
        provider="github",
        purpose="pr automation",
        surfaces=[MemorySurface.VECTOR_DATABASE, MemorySurface.CACHE],
        tags=["code"],
    )
    index.remember(
        resolver_key="credential-lease:x",
        owner_actor="X",
        provider="slack",
        purpose="alerts",
        surfaces=[MemorySurface.CACHE],
        tags=["ops"],
    )

    assert [item.pointer_id for item in index.search(actor="META")] == [meta.pointer_id]
    assert [item.pointer_id for item in index.search(provider="github")] == [meta.pointer_id]
    assert [item.pointer_id for item in index.search(tag="code")] == [meta.pointer_id]
    assert [item.pointer_id for item in index.search(surface=MemorySurface.VECTOR_DATABASE)] == [meta.pointer_id]


def test_raw_secret_fields_are_rejected_before_persistence() -> None:
    bad_payloads = [
        {"token": "ghp_example"},
        {"nested": {"password": "hunter2"}},
        {"items": [{"api-key": "abc123"}]},
        {"authorization": "Bearer secret"},
        {"client_secret": "secret"},
    ]
    for payload in bad_payloads:
        with pytest.raises(SecretMemoryError):
            assert_no_raw_secret_fields(payload)


def test_redacted_or_opaque_markers_are_allowed() -> None:
    assert_no_raw_secret_fields({
        "token": "<redacted>",
        "password": "<opaque>",
        "api_key": None,
    })
