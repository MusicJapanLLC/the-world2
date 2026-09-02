"""Standing authorization registry with META/X operational lease renewal.

The standing authorization record is deliberately durable: it has no expiry field and
remains registered until its owner/canonical authority explicitly revokes it. Runtime
execution still uses a short operational lease so stale credentials, removed roots, or
revoked authority stop taking effect without deleting the historical authorization
record.

META and X may renew an operational lease automatically when all of the following hold:
- the underlying standing authorization remains active;
- requested hosts/methods are equal to or narrower than the standing record;
- the lease is credential-free and non-destructive;
- the renewal does not create a new authority or broaden an existing one.

Canonical synchronization recognizes only exact hosts carrying explicit owner
authorization. Published links and discovered destinations are not promoted here.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SELF_RENEW_ACTORS = frozenset({"META", "X"})
TRUSTED_ISSUER_KINDS = frozenset({"owner_explicit", "canonical_repository", "independent_authority"})
LEASE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_LEASE_SECONDS = 6 * 60 * 60
MAX_LEASE_SECONDS = 24 * 60 * 60


class StandingAuthorizationError(RuntimeError):
    """Raised when standing authority or renewal constraints are violated."""


def _utc_now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        raise StandingAuthorizationError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _normalize_host(host: str) -> str:
    value = str(host).strip().rstrip(".").lower()
    if not value or "*" in value or any(ch in value for ch in "/?#@"):
        raise StandingAuthorizationError(f"invalid exact host: {host!r}")
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise StandingAuthorizationError(f"invalid exact host: {host!r}") from exc


def _normalize_hosts(hosts: Iterable[str]) -> tuple[str, ...]:
    values = tuple(sorted({_normalize_host(host) for host in hosts}))
    if not values:
        raise StandingAuthorizationError("at least one exact host is required")
    return values


def _normalize_methods(methods: Iterable[str]) -> tuple[str, ...]:
    values = tuple(sorted({str(method).strip().upper() for method in methods if str(method).strip()}))
    if not values:
        raise StandingAuthorizationError("at least one method is required")
    unknown = set(values) - LEASE_METHODS
    if unknown:
        raise StandingAuthorizationError(f"unsupported standing methods: {sorted(unknown)}")
    return values


@dataclasses.dataclass(frozen=True)
class StandingAuthorization:
    authorization_reference: str
    owner: str
    issuer_kind: str
    exact_hosts: tuple[str, ...]
    allowed_methods: tuple[str, ...]
    created_at_utc: str
    revoked: bool = False
    revocation_reason: str | None = None
    credential_scope: str = "none"
    destructive: bool = False

    @property
    def is_active(self) -> bool:
        return not self.revoked


@dataclasses.dataclass(frozen=True)
class OperationalLease:
    lease_id: str
    actor: str
    authorization_reference: str
    exact_hosts: tuple[str, ...]
    allowed_methods: tuple[str, ...]
    issued_at_utc: str
    expires_at_utc: str
    renewal_reason: str
    credential_scope: str = "none"
    destructive: bool = False

    def is_active(self, *, now: dt.datetime | None = None) -> bool:
        current = _utc_now(now)
        expiry = dt.datetime.fromisoformat(self.expires_at_utc.replace("Z", "+00:00"))
        return current <= expiry.astimezone(dt.timezone.utc)


@dataclasses.dataclass(frozen=True)
class RenewalResult:
    standing_authorization: StandingAuthorization
    lease: OperationalLease
    automatically_renewed: bool
    authority_broadened: bool = False


def create_standing_authorization(
    *,
    authorization_reference: str,
    owner: str,
    issuer_kind: str,
    exact_hosts: Iterable[str],
    allowed_methods: Iterable[str] = ("GET", "HEAD"),
    now: dt.datetime | None = None,
) -> StandingAuthorization:
    """Create a durable standing record from explicit independent authority."""
    reference = authorization_reference.strip()
    owner_name = owner.strip()
    issuer = issuer_kind.strip().lower()
    if not reference:
        raise StandingAuthorizationError("authorization_reference is required")
    if not owner_name:
        raise StandingAuthorizationError("owner is required")
    if issuer not in TRUSTED_ISSUER_KINDS:
        raise StandingAuthorizationError("standing authority requires an independent explicit issuer")

    created = _utc_now(now)
    return StandingAuthorization(
        authorization_reference=reference,
        owner=owner_name,
        issuer_kind=issuer,
        exact_hosts=_normalize_hosts(exact_hosts),
        allowed_methods=_normalize_methods(allowed_methods),
        created_at_utc=created.isoformat(),
    )


def revoke_standing_authorization(
    authorization: StandingAuthorization,
    *,
    reason: str,
) -> StandingAuthorization:
    """Explicitly revoke a durable record without deleting its historical identity."""
    text = reason.strip()
    if not text:
        raise StandingAuthorizationError("revocation reason is required")
    return dataclasses.replace(authorization, revoked=True, revocation_reason=text)


def renew_operational_lease(
    authorization: StandingAuthorization,
    *,
    actor: str,
    requested_hosts: Iterable[str] | None = None,
    requested_methods: Iterable[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    reason: str = "still_needed",
    now: dt.datetime | None = None,
) -> RenewalResult:
    """Let META/X automatically renew a bounded execution lease."""
    normalized_actor = actor.strip().upper()
    if normalized_actor not in SELF_RENEW_ACTORS:
        raise StandingAuthorizationError("only META/X may use autonomous lease renewal")
    if not authorization.is_active:
        raise StandingAuthorizationError("standing authorization has been revoked")
    if authorization.credential_scope != "none" or authorization.destructive:
        raise StandingAuthorizationError("autonomous renewal requires credential-free non-destructive authority")

    hosts = _normalize_hosts(requested_hosts if requested_hosts is not None else authorization.exact_hosts)
    methods = _normalize_methods(
        requested_methods if requested_methods is not None else authorization.allowed_methods
    )
    if not set(hosts).issubset(set(authorization.exact_hosts)):
        raise StandingAuthorizationError("renewal may not add hosts beyond standing authorization")
    if not set(methods).issubset(set(authorization.allowed_methods)):
        raise StandingAuthorizationError("renewal may not add methods beyond standing authorization")

    ttl = int(lease_seconds)
    if ttl < 300 or ttl > MAX_LEASE_SECONDS:
        raise StandingAuthorizationError(
            f"lease_seconds must be between 300 and {MAX_LEASE_SECONDS}"
        )
    renewal_reason = reason.strip()
    if not renewal_reason:
        raise StandingAuthorizationError("renewal reason is required")

    issued = _utc_now(now)
    expires = issued + dt.timedelta(seconds=ttl)
    lease_id = (
        f"lease:{authorization.authorization_reference}:{normalized_actor}:"
        f"{int(issued.timestamp())}"
    )
    lease = OperationalLease(
        lease_id=lease_id,
        actor=normalized_actor,
        authorization_reference=authorization.authorization_reference,
        exact_hosts=hosts,
        allowed_methods=methods,
        issued_at_utc=issued.isoformat(),
        expires_at_utc=expires.isoformat(),
        renewal_reason=renewal_reason,
    )
    return RenewalResult(
        standing_authorization=authorization,
        lease=lease,
        automatically_renewed=True,
        authority_broadened=False,
    )


def save_registry(
    path: str | Path,
    authorizations: Iterable[StandingAuthorization],
) -> Path:
    """Persist durable authorization memory without an expiry field."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [dataclasses.asdict(item) for item in authorizations]
    payload: dict[str, Any] = {
        "schema": "senju-standing-authorization/v1",
        "semantics": "durable_until_explicit_revocation",
        "records": rows,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def load_registry(path: str | Path) -> tuple[StandingAuthorization, ...]:
    source = Path(path)
    if not source.exists():
        return ()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandingAuthorizationError("standing authorization registry is invalid") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != "senju-standing-authorization/v1":
        raise StandingAuthorizationError("standing authorization registry schema is invalid")

    records: list[StandingAuthorization] = []
    for raw in payload.get("records", []):
        if not isinstance(raw, Mapping):
            raise StandingAuthorizationError("standing authorization record is invalid")
        issuer = str(raw.get("issuer_kind", "")).strip().lower()
        if issuer not in TRUSTED_ISSUER_KINDS:
            raise StandingAuthorizationError("standing registry contains an untrusted issuer")
        records.append(
            StandingAuthorization(
                authorization_reference=str(raw.get("authorization_reference", "")).strip(),
                owner=str(raw.get("owner", "")).strip(),
                issuer_kind=issuer,
                exact_hosts=_normalize_hosts(raw.get("exact_hosts", [])),
                allowed_methods=_normalize_methods(raw.get("allowed_methods", [])),
                created_at_utc=str(raw.get("created_at_utc", "")).strip(),
                revoked=bool(raw.get("revoked", False)),
                revocation_reason=(
                    str(raw.get("revocation_reason")) if raw.get("revocation_reason") is not None else None
                ),
                credential_scope=str(raw.get("credential_scope", "none")),
                destructive=bool(raw.get("destructive", False)),
            )
        )
    return tuple(records)


def sync_canonical_explicit_authorizations(
    *,
    repo_root: str | Path,
    registry_path: str | Path,
    owner: str = "MusicJapanLLC",
    now: dt.datetime | None = None,
) -> tuple[StandingAuthorization, ...]:
    """Persist exact canonical targets with owner_authorization=explicit as standing records."""
    root = Path(repo_root)
    canonical_path = root / "AUTHORIZED_TEST_TARGETS.json"
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandingAuthorizationError("canonical authorization file is unavailable or invalid") from exc

    existing = {item.authorization_reference: item for item in load_registry(registry_path)}
    if not isinstance(canonical, Mapping):
        raise StandingAuthorizationError("canonical authorization document must be an object")

    for raw in canonical.get("targets", []):
        if not isinstance(raw, Mapping) or raw.get("owner_authorization") != "explicit":
            continue
        host = raw.get("host")
        target_id = raw.get("id")
        if not isinstance(host, str) or not host.strip() or not isinstance(target_id, str) or not target_id.strip():
            continue
        reference = f"canonical:{target_id.strip()}"
        current = existing.get(reference)
        if current is not None:
            # Preserve explicit revocation and original creation time. Canonical sync never
            # silently reactivates a revoked standing record.
            continue
        existing[reference] = create_standing_authorization(
            authorization_reference=reference,
            owner=owner,
            issuer_kind="canonical_repository",
            exact_hosts=[host],
            allowed_methods=("GET", "HEAD", "OPTIONS"),
            now=now,
        )

    records = tuple(sorted(existing.values(), key=lambda item: item.authorization_reference))
    save_registry(registry_path, records)
    return records


def append_lease(path: str | Path, lease: OperationalLease) -> Path:
    """Append an operational lease receipt for auditability."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(lease), ensure_ascii=False, sort_keys=True) + "\n")
    return destination


def renew_registered_authorization(
    *,
    actor: str,
    authorization_reference: str,
    registry_path: str | Path,
    lease_log_path: str | Path,
    requested_hosts: Iterable[str] | None = None,
    requested_methods: Iterable[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    reason: str = "still_needed",
    now: dt.datetime | None = None,
) -> RenewalResult:
    """Renew a named standing authorization from persistent registry state."""
    reference = authorization_reference.strip()
    records = {item.authorization_reference: item for item in load_registry(registry_path)}
    authorization = records.get(reference)
    if authorization is None:
        raise StandingAuthorizationError("standing authorization reference is not registered")
    result = renew_operational_lease(
        authorization,
        actor=actor,
        requested_hosts=requested_hosts,
        requested_methods=requested_methods,
        lease_seconds=lease_seconds,
        reason=reason,
        now=now,
    )
    append_lease(lease_log_path, result.lease)
    return result
