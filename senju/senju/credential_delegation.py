"""Destination-bound credential delegation for recursive trusted-scope traversal.

This module deliberately never forwards a source host's raw credential to another
host. Cross-host traversal is represented by a short-lived, audience-bound lease
reference that a credential broker may redeem for the destination service.
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterable


class CredentialDelegationError(RuntimeError):
    """Raised when a delegated credential lease is invalid."""


def _host(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CredentialDelegationError(f"invalid URL for credential delegation: {url!r}")
    return parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")


@dataclass(frozen=True)
class CredentialLease:
    """Opaque reference to a destination-scoped credential.

    ``lease_id`` is intentionally not the credential itself. The secret material
    stays inside the broker/secret store and is redeemed only for ``audience_host``.
    """

    lease_id: str
    audience_host: str
    issued_at: float
    expires_at: float
    scopes: frozenset[str] = frozenset()
    parent_lease_id: str | None = None

    def validate_for(self, url: str, *, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        destination = _host(url)
        if destination != self.audience_host:
            raise CredentialDelegationError(
                f"credential lease audience mismatch: {self.audience_host} != {destination}"
            )
        if current >= self.expires_at:
            raise CredentialDelegationError("credential lease is expired")
        if not self.lease_id.strip():
            raise CredentialDelegationError("credential lease id is empty")


class CredentialDelegator:
    """Mint destination-bound leases without exposing raw credential material."""

    def __init__(
        self,
        issuer: Callable[[str, str, CredentialLease | None, frozenset[str], float], str],
        *,
        ttl_seconds: float = 300.0,
        default_scopes: Iterable[str] = (),
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._issuer = issuer
        self.ttl_seconds = max(5.0, min(float(ttl_seconds), 3600.0))
        self.default_scopes = frozenset(str(scope).strip() for scope in default_scopes if str(scope).strip())
        self._clock = clock or time.time

    def delegate(
        self,
        source_url: str,
        destination_url: str,
        parent: CredentialLease | None = None,
        *,
        scopes: Iterable[str] | None = None,
    ) -> CredentialLease:
        source_host = _host(source_url)
        destination_host = _host(destination_url)
        now = float(self._clock())
        selected_scopes = (
            self.default_scopes
            if scopes is None
            else frozenset(str(scope).strip() for scope in scopes if str(scope).strip())
        )

        if parent is not None:
            parent.validate_for(source_url, now=now)

        # Same-host navigation can reuse the current lease. Cross-host navigation
        # always mints a new destination-bound lease rather than forwarding secrets.
        if parent is not None and source_host == destination_host:
            return parent

        lease_id = str(
            self._issuer(source_host, destination_host, parent, selected_scopes, self.ttl_seconds)
        ).strip()
        if not lease_id:
            raise CredentialDelegationError("credential issuer returned an empty lease id")

        lease = CredentialLease(
            lease_id=lease_id,
            audience_host=destination_host,
            issued_at=now,
            expires_at=now + self.ttl_seconds,
            scopes=selected_scopes,
            parent_lease_id=None if parent is None else parent.lease_id,
        )
        lease.validate_for(destination_url, now=now)
        return lease
