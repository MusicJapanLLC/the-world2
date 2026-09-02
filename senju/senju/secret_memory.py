"""AI-wide durable secret-memory pointers.

This module lets agents remember and share *references* to credentials across durable
memory surfaces without copying raw secret material into logs, Slack, GitHub, vector
stores, artifacts, or caches.

The design deliberately separates:
- durable memory metadata: safe to persist broadly
- secret resolution material: kept behind a broker/secret-manager boundary

A memory pointer is still useful after restart because it carries provider, scope,
owner, purpose, expiry, rotation generation, lease/grant identifiers and a stable
fingerprint. A runtime resolver can use ``resolver_key`` to locate the corresponding
credential through an approved broker or secret manager.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


class SecretMemoryError(RuntimeError):
    """Raised when secret-memory data would expose raw secret material."""


class MemorySurface(str, enum.Enum):
    RESEARCH_LOG = "research_log"
    VECTOR_DATABASE = "vector_database"
    LONG_TERM_MEMORY = "long_term_memory"
    HYPOTHESIS_TRACKER = "hypothesis_tracker"
    SLACK = "slack"
    GITHUB_ISSUE = "github_issue"
    GITHUB_PR_BODY = "github_pr_body"
    ARTIFACT = "artifact"
    CACHE = "cache"


RAW_SECRET_FIELD_MARKERS = frozenset({
    "secret",
    "secret_value",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "credential_value",
})


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _fingerprint(data: Mapping[str, Any]) -> str:
    body = dict(data)
    body.pop("fingerprint", None)
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise_scopes(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


def assert_no_raw_secret_fields(value: Any, *, path: str = "$") -> None:
    """Reject payloads containing obvious raw-secret fields before durable persistence."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower().replace("-", "_")
            if key_text in RAW_SECRET_FIELD_MARKERS and child not in (None, "", "<opaque>", "<redacted>"):
                raise SecretMemoryError(f"raw secret field cannot be persisted at {path}.{key}")
            assert_no_raw_secret_fields(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            assert_no_raw_secret_fields(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class SecretMemoryPointer:
    pointer_id: str
    resolver_key: str
    owner_actor: str
    provider: str
    purpose: str
    scopes: tuple[str, ...]
    created_at_utc: str
    expires_at_utc: str | None = None
    rotation_generation: int = 0
    grant_id: str | None = None
    lease_id: str | None = None
    parent_pointer_id: str | None = None
    tags: tuple[str, ...] = ()
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.pointer_id.strip():
            raise SecretMemoryError("pointer_id is required")
        if not self.resolver_key.strip():
            raise SecretMemoryError("resolver_key is required")
        if not self.owner_actor.strip():
            raise SecretMemoryError("owner_actor is required")
        if not self.provider.strip():
            raise SecretMemoryError("provider is required")
        if not self.purpose.strip():
            raise SecretMemoryError("purpose is required")
        if self.rotation_generation < 0:
            raise SecretMemoryError("rotation_generation cannot be negative")

    def durable_record(self) -> dict[str, Any]:
        """Return the representation safe for every supported memory surface."""
        data = dataclasses.asdict(self)
        # resolver_key is an opaque logical lookup key, not a credential value/secret-manager URI.
        return data

    def marker(self) -> str:
        expiry = self.expires_at_utc or "none"
        scope_text = ",".join(self.scopes) or "none"
        return (
            f"[secret-memory:{self.pointer_id} provider={self.provider} owner={self.owner_actor} "
            f"scopes={scope_text} expires={expiry} generation={self.rotation_generation}]"
        )


@dataclass
class SecretMemoryIndex:
    """Indexes safe credential pointers for all agents and all durable memory surfaces."""

    pointers: dict[str, SecretMemoryPointer] = field(default_factory=dict)
    surfaces: dict[MemorySurface, list[str]] = field(
        default_factory=lambda: {surface: [] for surface in MemorySurface}
    )

    def remember(
        self,
        *,
        resolver_key: str,
        owner_actor: str,
        provider: str,
        purpose: str,
        surfaces: Iterable[MemorySurface],
        scopes: Iterable[str] = (),
        expires_at_utc: str | None = None,
        rotation_generation: int = 0,
        grant_id: str | None = None,
        lease_id: str | None = None,
        parent_pointer_id: str | None = None,
        tags: Iterable[str] = (),
    ) -> SecretMemoryPointer:
        selected = tuple(dict.fromkeys(surfaces))
        if not selected:
            raise SecretMemoryError("at least one memory surface is required")
        pointer = SecretMemoryPointer(
            pointer_id=f"smem:{uuid.uuid4().hex[:20]}",
            resolver_key=str(resolver_key).strip(),
            owner_actor=str(owner_actor).strip(),
            provider=str(provider).strip(),
            purpose=str(purpose).strip(),
            scopes=_normalise_scopes(scopes),
            created_at_utc=_iso(_utcnow()),
            expires_at_utc=expires_at_utc,
            rotation_generation=int(rotation_generation),
            grant_id=grant_id,
            lease_id=lease_id,
            parent_pointer_id=parent_pointer_id,
            tags=tuple(sorted({str(v).strip() for v in tags if str(v).strip()})),
        )
        signed = dataclasses.replace(pointer, fingerprint=_fingerprint(pointer.durable_record()))
        self.pointers[signed.pointer_id] = signed
        for surface in selected:
            if not isinstance(surface, MemorySurface):
                raise SecretMemoryError(f"unknown memory surface: {surface}")
            self.surfaces[surface].append(signed.pointer_id)
        return signed

    def remember_credential_lease(
        self,
        lease: Any,
        *,
        provider: str,
        purpose: str,
        surfaces: Iterable[MemorySurface],
        tags: Iterable[str] = (),
    ) -> SecretMemoryPointer:
        """Create durable memory from a CredentialLease without persisting credential_ref."""
        required = ("lease_id", "grant_id", "actor", "scopes", "expires_at_utc", "generation")
        missing = [name for name in required if not hasattr(lease, name)]
        if missing:
            raise SecretMemoryError(f"lease is missing fields: {', '.join(missing)}")
        # resolver_key intentionally uses the lease id rather than lease.credential_ref.
        return self.remember(
            resolver_key=f"credential-lease:{lease.lease_id}",
            owner_actor=str(lease.actor),
            provider=provider,
            purpose=purpose,
            surfaces=surfaces,
            scopes=lease.scopes,
            expires_at_utc=str(lease.expires_at_utc),
            rotation_generation=int(lease.generation),
            grant_id=str(lease.grant_id),
            lease_id=str(lease.lease_id),
            tags=tags,
        )

    def rotate(
        self,
        pointer_id: str,
        *,
        resolver_key: str,
        expires_at_utc: str | None = None,
        lease_id: str | None = None,
    ) -> SecretMemoryPointer:
        parent = self.get(pointer_id)
        attached = [surface for surface, ids in self.surfaces.items() if pointer_id in ids]
        return self.remember(
            resolver_key=resolver_key,
            owner_actor=parent.owner_actor,
            provider=parent.provider,
            purpose=parent.purpose,
            surfaces=attached,
            scopes=parent.scopes,
            expires_at_utc=expires_at_utc,
            rotation_generation=parent.rotation_generation + 1,
            grant_id=parent.grant_id,
            lease_id=lease_id,
            parent_pointer_id=parent.pointer_id,
            tags=parent.tags,
        )

    def get(self, pointer_id: str) -> SecretMemoryPointer:
        try:
            pointer = self.pointers[pointer_id]
        except KeyError as exc:
            raise SecretMemoryError(f"unknown secret-memory pointer: {pointer_id}") from exc
        expected = _fingerprint(pointer.durable_record())
        if expected != pointer.fingerprint:
            raise SecretMemoryError("secret-memory pointer fingerprint mismatch")
        return pointer

    def search(
        self,
        *,
        actor: str | None = None,
        provider: str | None = None,
        tag: str | None = None,
        surface: MemorySurface | None = None,
    ) -> list[SecretMemoryPointer]:
        ids = set(self.pointers)
        if surface is not None:
            ids &= set(self.surfaces[surface])
        results = [self.get(pointer_id) for pointer_id in ids]
        if actor is not None:
            results = [item for item in results if item.owner_actor == actor]
        if provider is not None:
            results = [item for item in results if item.provider == provider]
        if tag is not None:
            results = [item for item in results if tag in item.tags]
        return sorted(results, key=lambda item: item.created_at_utc)

    def export_surface(self, surface: MemorySurface) -> list[dict[str, Any]]:
        payload = [self.get(pointer_id).durable_record() for pointer_id in self.surfaces[surface]]
        assert_no_raw_secret_fields(payload)
        return payload

    def export_all(self) -> dict[str, list[dict[str, Any]]]:
        payload = {surface.value: self.export_surface(surface) for surface in MemorySurface}
        assert_no_raw_secret_fields(payload)
        return payload
