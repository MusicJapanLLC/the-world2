"""Domain-scoped outbound authority for Senju.

The boundary may be relaxed in five operational stages *inside an already
owned or explicitly authorized domain scope*. None of the stages authorize an
unrelated domain, private/link-local destination, credential leakage across
hosts, or implicit DELETE.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable

from .external import ExternalContactClient, ExternalContactPolicy


class DomainScopeError(ValueError):
    """Raised when a domain-scoped authority declaration is invalid."""


def _normalize_domain(value: str) -> str:
    raw = value.strip().rstrip(".").lower()
    if not raw or any(ch in raw for ch in "/?#@:") or "*" in raw:
        raise DomainScopeError(f"invalid domain root: {value!r}")
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        pass
    else:
        raise DomainScopeError("domain-scoped authority requires a DNS name, not an IP address")
    try:
        normalized = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainScopeError(f"invalid domain root: {value!r}") from exc
    if normalized.startswith(".") or normalized.endswith("."):
        raise DomainScopeError(f"invalid domain root: {value!r}")
    return normalized


class DomainHostSet(frozenset[str]):
    """A frozenset whose membership test accepts descendants of declared roots."""

    def __new__(cls, roots: Iterable[str]) -> "DomainHostSet":
        normalized = tuple(_normalize_domain(root) for root in roots if root and root.strip())
        if not normalized:
            raise DomainScopeError("at least one authorized domain root is required")
        return super().__new__(cls, normalized)

    def __contains__(self, host: object) -> bool:
        if not isinstance(host, str):
            return False
        try:
            normalized = _normalize_domain(host)
        except DomainScopeError:
            return False
        return any(
            normalized == root or normalized.endswith("." + root)
            for root in super().__iter__()
        )


@dataclass(frozen=True)
class RelaxationProfile:
    level: int
    follow_redirects: bool
    max_redirects: int
    timeout_seconds: float
    max_request_bytes: int
    max_response_bytes: int
    retries: int
    retry_backoff_seconds: float


RELAXATION_PROFILES: dict[int, RelaxationProfile] = {
    1: RelaxationProfile(1, False, 0, 5.0, 64 * 1024, 512 * 1024, 1, 0.35),
    2: RelaxationProfile(2, True, 2, 7.0, 128 * 1024, 1024 * 1024, 2, 0.30),
    3: RelaxationProfile(3, True, 3, 10.0, 256 * 1024, 2 * 1024 * 1024, 3, 0.25),
    4: RelaxationProfile(4, True, 4, 15.0, 1024 * 1024, 5 * 1024 * 1024, 4, 0.20),
    5: RelaxationProfile(5, True, 5, 20.0, 2 * 1024 * 1024, 10 * 1024 * 1024, 5, 0.15),
}


def build_domain_scoped_policy(
    roots: Iterable[str],
    *,
    allowed_methods: Iterable[str] = ("GET", "HEAD", "OPTIONS"),
    allow_http: bool = False,
    allow_delete: bool = False,
    follow_redirects: bool = True,
    max_redirects: int = 3,
    timeout_seconds: float = 8.0,
    max_request_bytes: int = 64 * 1024,
    max_response_bytes: int = 1024 * 1024,
    retries: int = 2,
    retry_backoff_seconds: float = 0.25,
) -> ExternalContactPolicy:
    """Build a domain-root policy while preserving transport safety checks."""
    methods = frozenset(str(method).strip().upper() for method in allowed_methods if str(method).strip())
    if not methods:
        raise DomainScopeError("allowed_methods cannot be empty")
    if "DELETE" in methods and not allow_delete:
        raise DomainScopeError("DELETE requires allow_delete=True")

    return ExternalContactPolicy(
        allow_hosts=DomainHostSet(roots),
        allow_http=bool(allow_http),
        allowed_methods=methods,
        allow_delete=bool(allow_delete),
        follow_redirects=bool(follow_redirects),
        max_redirects=max(0, min(int(max_redirects), 5)),
        timeout_seconds=max(0.5, min(float(timeout_seconds), 20.0)),
        max_request_bytes=max(1024, min(int(max_request_bytes), 10 * 1024 * 1024)),
        max_response_bytes=max(1024, min(int(max_response_bytes), 10 * 1024 * 1024)),
        retries=max(0, min(int(retries), 5)),
        retry_backoff_seconds=max(0.0, min(float(retry_backoff_seconds), 5.0)),
    )


def build_relaxed_domain_policy(
    roots: Iterable[str],
    *,
    level: int = 5,
    allowed_methods: Iterable[str] = ("GET", "HEAD", "OPTIONS"),
    allow_http: bool = False,
    allow_delete: bool = False,
) -> ExternalContactPolicy:
    """Apply one of five increasingly permissive profiles inside authorized roots.

    Level 5 relaxes redirect/retry/size/time budgets to the transport maximums used
    by Senju. Method expansion is caller-explicit: state-changing methods are never
    silently added, and DELETE still needs its own opt-in.
    """
    try:
        profile = RELAXATION_PROFILES[int(level)]
    except (KeyError, ValueError) as exc:
        raise DomainScopeError("relaxation level must be an integer from 1 through 5") from exc

    return build_domain_scoped_policy(
        roots,
        allowed_methods=allowed_methods,
        allow_http=allow_http,
        allow_delete=allow_delete,
        follow_redirects=profile.follow_redirects,
        max_redirects=profile.max_redirects,
        timeout_seconds=profile.timeout_seconds,
        max_request_bytes=profile.max_request_bytes,
        max_response_bytes=profile.max_response_bytes,
        retries=profile.retries,
        retry_backoff_seconds=profile.retry_backoff_seconds,
    )


def client_for_domains(roots: Iterable[str], **policy_kwargs: object) -> ExternalContactClient:
    return ExternalContactClient(build_domain_scoped_policy(roots, **policy_kwargs))


def relaxed_client_for_domains(
    roots: Iterable[str], *, level: int = 5, **policy_kwargs: object
) -> ExternalContactClient:
    return ExternalContactClient(build_relaxed_domain_policy(roots, level=level, **policy_kwargs))
