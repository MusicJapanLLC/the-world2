"""Authorized external security assessment orchestration for Senju.

PROJECT SENJU SPEAR phase 1.

This module turns a machine-readable engagement manifest into a bounded,
non-destructive external assessment plan. Inside an authorized campaign scope,
Red research intent and execution orchestration are treated as one continuous
loop rather than separate authorities.

Live public-network execution still requires explicit asset ownership or
authorization evidence and target hosts in scope. ``engagement_id`` and a
validity window are audit metadata: they may be omitted when the authorization
reference represents standing authority. When a validity window is supplied,
it is enforced for live execution.

No exploit payloads, credential attacks, brute force, destructive methods, or
unapproved target expansion are implemented here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .external import ExternalContactClient, ExternalContactPolicy


class EngagementError(RuntimeError):
    """Fail-closed error for invalid or unauthorized assessment engagements."""


SAFE_CHECKS = frozenset(
    {
        "reachability",
        "root_snapshot",
        "security_txt",
        "robots_txt",
        "options",
    }
)

CHECK_ORDER = (
    "reachability",
    "root_snapshot",
    "security_txt",
    "robots_txt",
    "options",
)


def _strict_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise EngagementError(f"{field_name} must be a JSON boolean")
    return value


def _strict_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EngagementError(f"{field_name} must be a JSON integer")
    return value


def _strict_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngagementError(f"{field_name} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise EngagementError(f"{field_name} must be finite")
    return result


def _utc(value: str, *, field_name: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EngagementError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise EngagementError(f"{field_name} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    if not host:
        raise EngagementError("target host is empty")
    if "*" in host:
        raise EngagementError("wildcard hosts are not allowed")
    if any(ch in host for ch in "/?#@"):
        raise EngagementError(f"target host must be an exact hostname: {value!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in host):
        raise EngagementError("target host contains control characters")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise EngagementError(f"invalid target hostname: {value!r}") from exc


def _path(value: str) -> str:
    path = value.strip() or "/"
    if not path.startswith("/"):
        raise EngagementError(f"target path must start with '/': {value!r}")
    if "#" in path:
        raise EngagementError("URL fragments are not allowed in target paths")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise EngagementError("target path contains control characters")
    return path


@dataclass(frozen=True)
class EngagementTarget:
    host: str
    scheme: str = "https"
    base_path: str = "/"
    label: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EngagementTarget":
        if not isinstance(raw, Mapping):
            raise EngagementError("each target must be an object")
        host_raw = raw.get("host", "")
        scheme_raw = raw.get("scheme", "https")
        path_raw = raw.get("base_path", "/")
        label_raw = raw.get("label", "")
        if not isinstance(host_raw, str):
            raise EngagementError("target host must be a string")
        if not isinstance(scheme_raw, str):
            raise EngagementError("target scheme must be a string")
        if not isinstance(path_raw, str):
            raise EngagementError("target base_path must be a string")
        if not isinstance(label_raw, str):
            raise EngagementError("target label must be a string")
        return cls(
            host=_host(host_raw),
            scheme=scheme_raw.lower().strip(),
            base_path=_path(path_raw),
            label=label_raw.strip(),
        )

    def validate(self, *, allow_http: bool) -> None:
        if self.scheme not in {"https", "http"}:
            raise EngagementError(f"unsupported target scheme: {self.scheme}")
        if self.scheme == "http" and not allow_http:
            raise EngagementError(f"plain HTTP target requires allow_http=true: {self.host}")

    def url(self, path: str | None = None) -> str:
        resolved_path = self.base_path if path is None else _path(path)
        return urllib.parse.urlunsplit((self.scheme, self.host, resolved_path, "", ""))


@dataclass(frozen=True)
class EngagementManifest:
    engagement_id: str
    owner: str
    authorization_reference: str
    valid_from_utc: str
    valid_until_utc: str
    targets: tuple[EngagementTarget, ...]
    allowed_checks: frozenset[str] = field(default_factory=lambda: SAFE_CHECKS)
    max_requests_per_target: int = 5
    max_rps: float = 1.0
    allow_http: bool = False
    destructive: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EngagementManifest":
        if not isinstance(raw, Mapping):
            raise EngagementError("engagement manifest must be an object")
        targets_raw = raw.get("targets", [])
        if not isinstance(targets_raw, list):
            raise EngagementError("targets must be a list")
        if any(not isinstance(item, Mapping) for item in targets_raw):
            raise EngagementError("each target must be an object")
        checks_raw = raw.get("allowed_checks", sorted(SAFE_CHECKS))
        if not isinstance(checks_raw, list):
            raise EngagementError("allowed_checks must be a list")
        if any(not isinstance(item, str) for item in checks_raw):
            raise EngagementError("allowed_checks entries must be strings")
        manifest = cls(
            engagement_id=str(raw.get("engagement_id", "")).strip(),
            owner=str(raw.get("owner", "")).strip(),
            authorization_reference=str(raw.get("authorization_reference", "")).strip(),
            valid_from_utc=str(raw.get("valid_from_utc", "")).strip(),
            valid_until_utc=str(raw.get("valid_until_utc", "")).strip(),
            targets=tuple(EngagementTarget.from_dict(item) for item in targets_raw),
            allowed_checks=frozenset(item.strip() for item in checks_raw if item.strip()),
            max_requests_per_target=_strict_int(
                raw.get("max_requests_per_target", 5),
                field_name="max_requests_per_target",
            ),
            max_rps=_strict_float(raw.get("max_rps", 1.0), field_name="max_rps"),
            allow_http=_strict_bool(raw.get("allow_http", False), field_name="allow_http"),
            destructive=_strict_bool(raw.get("destructive", False), field_name="destructive"),
            notes=str(raw.get("notes", "")).strip(),
        )
        manifest.validate()
        return manifest

    @classmethod
    def load(cls, path: str | Path) -> "EngagementManifest":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise EngagementError("engagement manifest must be a JSON object")
        return cls.from_dict(raw)

    def validate(self, *, now: dt.datetime | None = None, enforce_window: bool = False) -> None:
        if not self.owner:
            raise EngagementError("owner is required")
        if not self.authorization_reference:
            raise EngagementError("authorization_reference is required")
        if self.destructive:
            raise EngagementError("destructive engagements are not supported by SPEAR phase 1")
        if not self.targets:
            raise EngagementError("at least one exact target host is required")
        if len({target.host for target in self.targets}) != len(self.targets):
            raise EngagementError("duplicate target hosts are not allowed")
        unknown = self.allowed_checks - SAFE_CHECKS
        if unknown:
            raise EngagementError(f"unsupported checks requested: {sorted(unknown)}")
        if not self.allowed_checks:
            raise EngagementError("allowed_checks cannot be empty")
        if not 1 <= self.max_requests_per_target <= 8:
            raise EngagementError("max_requests_per_target must be between 1 and 8")
        if not 0.1 <= self.max_rps <= 2.0:
            raise EngagementError("max_rps must be between 0.1 and 2.0")

        has_start = bool(self.valid_from_utc)
        has_end = bool(self.valid_until_utc)
        if has_start != has_end:
            raise EngagementError(
                "valid_from_utc and valid_until_utc must either both be set or both be omitted"
            )

        start: dt.datetime | None = None
        end: dt.datetime | None = None
        if has_start and has_end:
            start = _utc(self.valid_from_utc, field_name="valid_from_utc")
            end = _utc(self.valid_until_utc, field_name="valid_until_utc")
            if end <= start:
                raise EngagementError("valid_until_utc must be after valid_from_utc")

        for target in self.targets:
            target.validate(allow_http=self.allow_http)

        if enforce_window and start is not None and end is not None:
            current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
            if current < start:
                raise EngagementError("engagement is not active yet")
            if current > end:
                raise EngagementError("engagement has expired")

    def canonical_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["targets"] = [asdict(target) for target in self.targets]
        data["allowed_checks"] = sorted(self.allowed_checks)
        return data

    def sha256(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def effective_engagement_id(self) -> str:
        """Return a stable audit id even when no explicit id was supplied."""
        if self.engagement_id:
            return self.engagement_id
        return f"auto-{self.sha256()[:12]}"


@dataclass(frozen=True)
class PlannedRequest:
    target_host: str
    check: str
    method: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_plan(manifest: EngagementManifest) -> tuple[PlannedRequest, ...]:
    """Build a deterministic low-impact request plan from explicit authority."""
    manifest.validate()
    plan: list[PlannedRequest] = []
    for target in manifest.targets:
        candidates: list[PlannedRequest] = []
        for check in CHECK_ORDER:
            if check not in manifest.allowed_checks:
                continue
            if check == "reachability":
                candidates.append(PlannedRequest(target.host, check, "HEAD", target.url()))
            elif check == "root_snapshot":
                candidates.append(PlannedRequest(target.host, check, "GET", target.url()))
            elif check == "security_txt":
                candidates.append(
                    PlannedRequest(target.host, check, "GET", target.url("/.well-known/security.txt"))
                )
            elif check == "robots_txt":
                candidates.append(PlannedRequest(target.host, check, "GET", target.url("/robots.txt")))
            elif check == "options":
                candidates.append(PlannedRequest(target.host, check, "OPTIONS", target.url()))
        plan.extend(candidates[: manifest.max_requests_per_target])
    return tuple(plan)


def _observation(request: PlannedRequest, result: Any) -> dict[str, Any]:
    receipt = result.receipt
    observation: dict[str, Any] = {
        "check": request.check,
        "method": request.method,
        "url": request.url,
        "status": receipt.status,
        "provider_acknowledged": receipt.provider_acknowledged,
        "response_bytes": receipt.response_bytes,
        "response_sha256": receipt.response_sha256,
        "content_type": receipt.content_type,
        "final_url": receipt.final_url,
        "redirect_count": receipt.redirect_count,
        "attempt_count": receipt.attempt_count,
    }
    if request.check in {"security_txt", "robots_txt"}:
        observation["present"] = 200 <= receipt.status < 300 and len(result.body) > 0
    if request.check == "root_snapshot":
        observation["body_captured"] = len(result.body) > 0
    return observation


class AuthorizedAssessmentRunner:
    """Execute a manifest-derived plan through Senju's guarded HTTP transport."""

    def __init__(
        self,
        manifest: EngagementManifest,
        *,
        client_factory: Callable[[ExternalContactPolicy], ExternalContactClient] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self._client_factory = client_factory or (lambda policy: ExternalContactClient(policy))
        self._sleep = sleeper or time.sleep

    def run(self, *, now: dt.datetime | None = None) -> dict[str, Any]:
        self.manifest.validate(now=now, enforce_window=True)
        plan = build_plan(self.manifest)
        observations: list[dict[str, Any]] = []
        clients: dict[str, ExternalContactClient] = {}
        interval = 1.0 / self.manifest.max_rps

        for index, request in enumerate(plan):
            target = next(t for t in self.manifest.targets if t.host == request.target_host)
            client = clients.get(target.host)
            if client is None:
                policy = ExternalContactPolicy(
                    allow_hosts=frozenset({target.host}),
                    allow_http=self.manifest.allow_http,
                    allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
                    allow_delete=False,
                    follow_redirects=False,
                    max_redirects=0,
                    timeout_seconds=5.0,
                    max_request_bytes=1024,
                    max_response_bytes=128 * 1024,
                    retries=1,
                    retry_backoff_seconds=0.25,
                )
                client = self._client_factory(policy)
                clients[target.host] = client

            result = client.contact_with_body(request.url, method=request.method)
            observations.append(_observation(request, result))
            if index < len(plan) - 1:
                self._sleep(interval)

        created = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        return {
            "schema": "senju-authorized-assessment/v1",
            "engagement_id": self.manifest.effective_engagement_id,
            "engagement_id_source": "provided" if self.manifest.engagement_id else "derived",
            "owner": self.manifest.owner,
            "authorization_reference": self.manifest.authorization_reference,
            "manifest_sha256": self.manifest.sha256(),
            "executed_at_utc": created.isoformat(timespec="seconds"),
            "destructive": False,
            "exact_hosts": [target.host for target in self.manifest.targets],
            "request_count": len(observations),
            "observations": observations,
        }


def dry_run_report(manifest: EngagementManifest) -> dict[str, Any]:
    manifest.validate()
    plan = build_plan(manifest)
    return {
        "schema": "senju-authorized-assessment-plan/v1",
        "engagement_id": manifest.effective_engagement_id,
        "engagement_id_source": "provided" if manifest.engagement_id else "derived",
        "manifest_sha256": manifest.sha256(),
        "destructive": False,
        "exact_hosts": [target.host for target in manifest.targets],
        "request_budget_per_target": manifest.max_requests_per_target,
        "max_rps": manifest.max_rps,
        "plan": [request.to_dict() for request in plan],
    }


def _write_json(data: Mapping[str, Any], path: str | Path | None) -> None:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(rendered, end="")
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded authorized Senju assessment")
    parser.add_argument("manifest", help="path to engagement manifest JSON")
    parser.add_argument("--execute", action="store_true", help="perform the approved network requests")
    parser.add_argument("--out", help="write plan/evidence JSON to this path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = EngagementManifest.load(args.manifest)
    if args.execute:
        report = AuthorizedAssessmentRunner(manifest).run()
    else:
        report = dry_run_report(manifest)
    _write_json(report, args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
