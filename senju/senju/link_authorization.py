"""Recursive link-derived authorization inside a persistent trusted scope.

A link may propagate authorization from an already-authorized URL to another URL,
but the propagation never expands the underlying Owner/BOSS trust boundary. In
other words, A -> B -> C works recursively only when every destination is already
covered by ``TrustedOwnerScope``.

Credential continuity is supported through destination-bound opaque leases. A
same-host hop may reuse the current lease; a cross-host hop requires the configured
``CredentialDelegator`` to mint a new lease for the destination host. Raw source
credentials are never copied across hosts.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

from .credential_delegation import (
    CredentialDelegationError,
    CredentialDelegator,
    CredentialLease,
)
from .trusted_scope import TrustedOwnerScope, TrustedScopeError


class LinkAuthorizationError(TrustedScopeError):
    """Raised when recursive link authorization violates the trusted scope."""


def _canonical_url(base_url: str, candidate: str | None = None) -> str:
    resolved = urllib.parse.urljoin(base_url, candidate) if candidate is not None else base_url
    parsed = urllib.parse.urlsplit(resolved)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise LinkAuthorizationError(f"unsupported link target: {resolved!r}")
    if parsed.username is not None or parsed.password is not None:
        raise LinkAuthorizationError("credentials in URL authority are not allowed")
    # Fragments do not change the authorization target.
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def _url_host(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname:
        raise LinkAuthorizationError(f"URL has no hostname: {url!r}")
    return parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "area", "link"}:
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)
                break


@dataclass(frozen=True)
class AuthorizationEdge:
    parent_url: str
    child_url: str
    depth: int
    credential_lease_id: str | None = None


class RecursiveLinkAuthorization:
    """Track recursive A -> B -> C authorization with explicit provenance.

    ``TrustedOwnerScope`` remains the hard boundary. A discovered link can inherit
    authorization only if its resolved target is already inside that persistent
    scope. Credential continuity is optional and uses opaque destination leases.
    """

    def __init__(
        self,
        scope: TrustedOwnerScope,
        *,
        max_depth: int = 8,
        max_urls: int = 1000,
        credential_delegator: CredentialDelegator | None = None,
    ) -> None:
        self.scope = scope
        self.max_depth = max(0, min(int(max_depth), 32))
        self.max_urls = max(1, min(int(max_urls), 100_000))
        self.credential_delegator = credential_delegator
        self._depth: dict[str, int] = {}
        self._parent: dict[str, str | None] = {}
        self._edges: list[AuthorizationEdge] = []
        self._credential_leases: dict[str, CredentialLease] = {}

    def seed(self, url: str, *, credential_lease: CredentialLease | None = None) -> str:
        target = _canonical_url(url)
        if not self.scope.allows_url(target):
            raise LinkAuthorizationError(f"seed is outside trusted owner scope: {target}")
        if credential_lease is not None:
            try:
                credential_lease.validate_for(target)
            except CredentialDelegationError as exc:
                raise LinkAuthorizationError(str(exc)) from exc
        self._remember(target, depth=0, parent=None, credential_lease=credential_lease)
        return target

    def inherit(self, parent_url: str, linked_url: str) -> str:
        parent = _canonical_url(parent_url)
        if parent not in self._depth:
            raise LinkAuthorizationError(f"parent URL is not authorized: {parent}")

        child = _canonical_url(parent, linked_url)
        if not self.scope.allows_url(child):
            raise LinkAuthorizationError(f"linked target is outside trusted owner scope: {child}")

        depth = self._depth[parent] + 1
        if depth > self.max_depth:
            raise LinkAuthorizationError(
                f"recursive link depth exceeds configured maximum ({self.max_depth})"
            )

        child_lease = self._lease_for_hop(parent, child)
        self._remember(child, depth=depth, parent=parent, credential_lease=child_lease)
        self._edges.append(
            AuthorizationEdge(
                parent_url=parent,
                child_url=child,
                depth=depth,
                credential_lease_id=None if child_lease is None else child_lease.lease_id,
            )
        )
        return child

    def ingest_html(self, parent_url: str, html: str) -> tuple[str, ...]:
        """Authorize all in-scope links found in one already-authorized document.

        Out-of-scope, malformed, mailto/javascript and otherwise unsupported links
        are ignored rather than weakening the persistent trusted scope.
        """
        parent = _canonical_url(parent_url)
        if parent not in self._depth:
            raise LinkAuthorizationError(f"parent URL is not authorized: {parent}")

        parser = _HrefParser()
        parser.feed(html)
        accepted: list[str] = []
        for href in parser.hrefs:
            try:
                child = self.inherit(parent, href)
            except (LinkAuthorizationError, TrustedScopeError, ValueError):
                continue
            if child not in accepted:
                accepted.append(child)
        return tuple(accepted)

    def is_authorized(self, url: str) -> bool:
        try:
            target = _canonical_url(url)
        except LinkAuthorizationError:
            return False
        return target in self._depth

    def depth_for(self, url: str) -> int | None:
        try:
            target = _canonical_url(url)
        except LinkAuthorizationError:
            return None
        return self._depth.get(target)

    def lineage(self, url: str) -> tuple[str, ...]:
        target = _canonical_url(url)
        if target not in self._depth:
            raise LinkAuthorizationError(f"URL is not authorized: {target}")
        chain: list[str] = []
        current: str | None = target
        while current is not None:
            chain.append(current)
            current = self._parent[current]
        chain.reverse()
        return tuple(chain)

    def credential_lease_for(self, url: str) -> CredentialLease | None:
        """Return the opaque lease metadata attached to an authorized URL."""
        target = _canonical_url(url)
        if target not in self._depth:
            raise LinkAuthorizationError(f"URL is not authorized: {target}")
        lease = self._credential_leases.get(target)
        if lease is not None:
            try:
                lease.validate_for(target)
            except CredentialDelegationError as exc:
                raise LinkAuthorizationError(str(exc)) from exc
        return lease

    @property
    def authorized_urls(self) -> frozenset[str]:
        return frozenset(self._depth)

    @property
    def authorized_hosts(self) -> frozenset[str]:
        hosts = {
            urllib.parse.urlsplit(url).hostname
            for url in self._depth
            if urllib.parse.urlsplit(url).hostname
        }
        return frozenset(str(host) for host in hosts)

    @property
    def edges(self) -> tuple[AuthorizationEdge, ...]:
        return tuple(self._edges)

    def _lease_for_hop(self, parent: str, child: str) -> CredentialLease | None:
        parent_lease = self._credential_leases.get(parent)
        if parent_lease is None:
            return None

        try:
            parent_lease.validate_for(parent)
        except CredentialDelegationError as exc:
            raise LinkAuthorizationError(str(exc)) from exc

        if _url_host(parent) == _url_host(child):
            return parent_lease

        if self.credential_delegator is None:
            # Fail closed: a cross-host hop never receives the source lease directly.
            return None

        try:
            child_lease = self.credential_delegator.delegate(parent, child, parent_lease)
            child_lease.validate_for(child)
        except CredentialDelegationError as exc:
            raise LinkAuthorizationError(str(exc)) from exc
        return child_lease

    def _remember(
        self,
        url: str,
        *,
        depth: int,
        parent: str | None,
        credential_lease: CredentialLease | None = None,
    ) -> None:
        existing = self._depth.get(url)
        if existing is None and len(self._depth) >= self.max_urls:
            raise LinkAuthorizationError(
                f"recursive authorization exceeds configured URL maximum ({self.max_urls})"
            )
        if existing is None or depth < existing:
            self._depth[url] = depth
            self._parent[url] = parent
        if credential_lease is not None:
            self._credential_leases[url] = credential_lease
