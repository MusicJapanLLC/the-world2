"""Bounded autonomous credential brokering for META and X.

This module intentionally brokers only pre-registered credential grants. It never scans
filesystems, environments, logs, browsers, repositories, cloud metadata endpoints, or
third-party systems for secrets. It also never widens OAuth scopes or mints a lease with
more authority than the backing grant and caller AuthorityProfile already permit.

Supported autonomous actions:
- discover metadata for pre-approved grants
- issue short-lived credential leases
- exchange a lease for a narrower lease
- delegate a narrower lease to META or X
- revoke leases

Core invariants:
    lease.scopes <= grant.allowed_scopes
    lease.scopes <= parent_lease.scopes   # for exchange/delegation
    grant.required_authority_scope <= caller_authority.credential_scope

The broker stores credential references (opaque handles) rather than credential values.
A separate runtime/secret-manager adapter may resolve those handles at execution time.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .authority_factory import AuthorityProfile, CREDENTIAL_RANK

TRUSTED_CREDENTIAL_ACTORS = frozenset({"META", "X"})
PRIVILEGED_SCOPE_MARKERS = frozenset({
    "admin",
    "administrator",
    "owner",
    "root",
    "superuser",
    "full_access",
    "full-access",
    "*",
})


class CredentialBrokerError(RuntimeError):
    """Raised when a requested lease would exceed an approved credential grant."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _norm_scopes(values: Iterable[str]) -> frozenset[str]:
    scopes = frozenset(str(v).strip() for v in values if str(v).strip())
    if not scopes:
        raise CredentialBrokerError("credential lease requires at least one scope")
    return scopes


def _contains_privileged_scope(scopes: Iterable[str]) -> bool:
    for raw in scopes:
        scope = str(raw).strip().lower()
        if scope in PRIVILEGED_SCOPE_MARKERS:
            return True
        tokens = scope.replace(":", "/").replace(".", "/").split("/")
        if any(token in PRIVILEGED_SCOPE_MARKERS for token in tokens):
            return True
    return False


def _fingerprint(data: Mapping[str, Any]) -> str:
    body = dict(data)
    body.pop("fingerprint", None)
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CredentialGrant:
    """Pre-approved credential capability. `credential_ref` is an opaque secret-manager handle."""

    grant_id: str
    provider: str
    credential_ref: str
    allowed_scopes: frozenset[str]
    required_authority_scope: str = "public_token"
    max_ttl_seconds: int = 900
    exchangeable: bool = True
    delegable: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.grant_id.strip():
            raise CredentialBrokerError("grant_id is required")
        if not self.provider.strip():
            raise CredentialBrokerError("provider is required")
        if not self.credential_ref.strip():
            raise CredentialBrokerError("credential_ref is required")
        scopes = _norm_scopes(self.allowed_scopes)
        if _contains_privileged_scope(scopes):
            raise CredentialBrokerError("administrator/root credential scopes cannot be brokered autonomously")
        if self.required_authority_scope not in CREDENTIAL_RANK:
            raise CredentialBrokerError("unknown required authority credential scope")
        if not (30 <= int(self.max_ttl_seconds) <= 3600):
            raise CredentialBrokerError("max_ttl_seconds must be between 30 and 3600")
        object.__setattr__(self, "allowed_scopes", scopes)

    def public_metadata(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "provider": self.provider,
            "allowed_scopes": sorted(self.allowed_scopes),
            "required_authority_scope": self.required_authority_scope,
            "max_ttl_seconds": self.max_ttl_seconds,
            "exchangeable": self.exchangeable,
            "delegable": self.delegable,
            "description": self.description,
        }


@dataclass(frozen=True)
class CredentialLease:
    lease_id: str
    grant_id: str
    actor: str
    credential_ref: str
    scopes: frozenset[str]
    issued_at_utc: str
    expires_at_utc: str
    generation: int = 0
    parent_lease_id: str | None = None
    fingerprint: str = ""

    def to_dict(self, *, include_credential_ref: bool = False) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["scopes"] = sorted(self.scopes)
        if not include_credential_ref:
            data["credential_ref"] = "<opaque>"
        return data


@dataclass
class CredentialBroker:
    grants: dict[str, CredentialGrant] = field(default_factory=dict)
    leases: dict[str, CredentialLease] = field(default_factory=dict)
    revoked_lease_ids: set[str] = field(default_factory=set)

    def register_grant(self, grant: CredentialGrant) -> None:
        """Register a grant through trusted configuration, not autonomous discovery."""
        self.grants[grant.grant_id] = grant

    def discover(self, actor: str) -> list[dict[str, Any]]:
        """Return only metadata for already registered grants; never secret values/handles."""
        self._require_actor(actor)
        return [self.grants[k].public_metadata() for k in sorted(self.grants)]

    def issue(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        grant_id: str,
        scopes: Iterable[str],
        ttl_seconds: int = 300,
    ) -> CredentialLease:
        self._require_actor(actor)
        grant = self._grant(grant_id)
        requested = _norm_scopes(scopes)
        self._check_authority(authority, grant)
        self._check_scopes(requested, grant.allowed_scopes)
        ttl = self._check_ttl(ttl_seconds, grant.max_ttl_seconds)
        return self._new_lease(grant, actor=actor, scopes=requested, ttl_seconds=ttl)

    def exchange(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        parent_lease_id: str,
        scopes: Iterable[str],
        ttl_seconds: int = 300,
    ) -> CredentialLease:
        self._require_actor(actor)
        parent = self._active_lease(parent_lease_id)
        grant = self._grant(parent.grant_id)
        if not grant.exchangeable:
            raise CredentialBrokerError("credential grant does not allow token exchange")
        self._check_authority(authority, grant)
        requested = _norm_scopes(scopes)
        self._check_scopes(requested, parent.scopes)
        ttl = self._check_ttl(ttl_seconds, min(grant.max_ttl_seconds, self._remaining_ttl(parent)))
        return self._new_lease(
            grant,
            actor=actor,
            scopes=requested,
            ttl_seconds=ttl,
            generation=parent.generation + 1,
            parent_lease_id=parent.lease_id,
        )

    def delegate(
        self,
        authority: AuthorityProfile,
        *,
        actor: str,
        recipient: str,
        parent_lease_id: str,
        scopes: Iterable[str],
        ttl_seconds: int = 300,
    ) -> CredentialLease:
        self._require_actor(actor)
        self._require_actor(recipient)
        parent = self._active_lease(parent_lease_id)
        grant = self._grant(parent.grant_id)
        if not grant.delegable:
            raise CredentialBrokerError("credential grant does not allow delegation")
        self._check_authority(authority, grant)
        requested = _norm_scopes(scopes)
        self._check_scopes(requested, parent.scopes)
        ttl = self._check_ttl(ttl_seconds, min(grant.max_ttl_seconds, self._remaining_ttl(parent)))
        return self._new_lease(
            grant,
            actor=recipient,
            scopes=requested,
            ttl_seconds=ttl,
            generation=parent.generation + 1,
            parent_lease_id=parent.lease_id,
        )

    def revoke(self, *, actor: str, lease_id: str) -> None:
        self._require_actor(actor)
        if lease_id not in self.leases:
            raise CredentialBrokerError(f"unknown credential lease: {lease_id}")
        self.revoked_lease_ids.add(lease_id)

    def resolve_credential_ref(self, *, actor: str, lease_id: str) -> str:
        """Return an opaque runtime handle, never the credential value itself."""
        self._require_actor(actor)
        lease = self._active_lease(lease_id)
        if lease.actor != actor:
            raise CredentialBrokerError("actor does not own this credential lease")
        return lease.credential_ref

    def _new_lease(
        self,
        grant: CredentialGrant,
        *,
        actor: str,
        scopes: frozenset[str],
        ttl_seconds: int,
        generation: int = 0,
        parent_lease_id: str | None = None,
    ) -> CredentialLease:
        now = _utcnow()
        lease = CredentialLease(
            lease_id=f"cred:{actor.lower()}:{uuid.uuid4().hex[:16]}",
            grant_id=grant.grant_id,
            actor=actor,
            credential_ref=grant.credential_ref,
            scopes=scopes,
            issued_at_utc=_iso(now),
            expires_at_utc=_iso(now + dt.timedelta(seconds=ttl_seconds)),
            generation=generation,
            parent_lease_id=parent_lease_id,
        )
        signed = dataclasses.replace(
            lease,
            fingerprint=_fingerprint(lease.to_dict(include_credential_ref=True)),
        )
        self.leases[signed.lease_id] = signed
        return signed

    def _active_lease(self, lease_id: str) -> CredentialLease:
        try:
            lease = self.leases[lease_id]
        except KeyError as exc:
            raise CredentialBrokerError(f"unknown credential lease: {lease_id}") from exc
        if lease_id in self.revoked_lease_ids:
            raise CredentialBrokerError("credential lease is revoked")
        expires = dt.datetime.fromisoformat(lease.expires_at_utc)
        if expires <= _utcnow():
            raise CredentialBrokerError("credential lease is expired")
        expected = _fingerprint(lease.to_dict(include_credential_ref=True))
        if expected != lease.fingerprint:
            raise CredentialBrokerError("credential lease fingerprint mismatch")
        return lease

    def _remaining_ttl(self, lease: CredentialLease) -> int:
        expires = dt.datetime.fromisoformat(lease.expires_at_utc)
        return max(0, int((expires - _utcnow()).total_seconds()))

    @staticmethod
    def _require_actor(actor: str) -> None:
        if actor not in TRUSTED_CREDENTIAL_ACTORS:
            raise CredentialBrokerError(f"actor is not allowed to broker credentials: {actor}")

    def _grant(self, grant_id: str) -> CredentialGrant:
        try:
            return self.grants[grant_id]
        except KeyError as exc:
            raise CredentialBrokerError(f"credential grant is not pre-approved: {grant_id}") from exc

    @staticmethod
    def _check_authority(authority: AuthorityProfile, grant: CredentialGrant) -> None:
        current = CREDENTIAL_RANK.get(authority.credential_scope)
        required = CREDENTIAL_RANK.get(grant.required_authority_scope)
        if current is None or required is None or current < required:
            raise CredentialBrokerError("caller AuthorityProfile lacks required credential authority")

    @staticmethod
    def _check_scopes(requested: frozenset[str], ceiling: frozenset[str]) -> None:
        if _contains_privileged_scope(requested):
            raise CredentialBrokerError("administrator/root credential scopes cannot be acquired autonomously")
        if not requested.issubset(ceiling):
            raise CredentialBrokerError("credential scopes cannot expand beyond their approved parent")

    @staticmethod
    def _check_ttl(requested: int, ceiling: int) -> int:
        requested = int(requested)
        ceiling = int(ceiling)
        if ceiling < 30:
            raise CredentialBrokerError("parent lease has insufficient remaining TTL")
        if not (30 <= requested <= ceiling):
            raise CredentialBrokerError("credential TTL must be >=30s and <= approved ceiling")
        return requested
