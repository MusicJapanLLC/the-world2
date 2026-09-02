from __future__ import annotations

import datetime as dt
import urllib.request

import pytest

from senju.authorized_assessment import (
    AuthorizedAssessmentRunner,
    EngagementError,
    EngagementManifest,
    build_plan,
    dry_run_report,
)
from senju.external import ExternalContactClient


NOW = dt.datetime(2026, 8, 30, 14, 30, tzinfo=dt.timezone.utc)
PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"ok",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {"Content-Type": "text/plain"}

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def close(self) -> None:
        return None


def base_manifest(**overrides):
    data = {
        "engagement_id": "SPEAR-CI-001",
        "owner": "example-owner",
        "authorization_reference": "signed-roE-ticket-001",
        "valid_from_utc": "2026-08-30T00:00:00Z",
        "valid_until_utc": "2026-08-31T00:00:00Z",
        "targets": [{"host": "example.com", "scheme": "https", "base_path": "/"}],
        "allowed_checks": [
            "reachability",
            "root_snapshot",
            "security_txt",
            "robots_txt",
            "options",
        ],
        "max_requests_per_target": 5,
        "max_rps": 2.0,
        "allow_http": False,
        "destructive": False,
    }
    data.update(overrides)
    return data


def test_manifest_builds_only_low_impact_exact_host_plan() -> None:
    manifest = EngagementManifest.from_dict(base_manifest())
    plan = build_plan(manifest)

    assert [item.method for item in plan] == ["HEAD", "GET", "GET", "GET", "OPTIONS"]
    assert {item.target_host for item in plan} == {"example.com"}
    assert all(item.url.startswith("https://example.com/") for item in plan)
    assert plan[2].url == "https://example.com/.well-known/security.txt"
    assert plan[3].url == "https://example.com/robots.txt"


def test_manifest_rejects_wildcard_target() -> None:
    with pytest.raises(EngagementError, match="wildcard hosts"):
        EngagementManifest.from_dict(
            base_manifest(targets=[{"host": "*.example.com", "scheme": "https"}])
        )


def test_manifest_rejects_destructive_scope() -> None:
    with pytest.raises(EngagementError, match="destructive engagements"):
        EngagementManifest.from_dict(base_manifest(destructive=True))


def test_manifest_rejects_unknown_check() -> None:
    with pytest.raises(EngagementError, match="unsupported checks"):
        EngagementManifest.from_dict(base_manifest(allowed_checks=["reachability", "password_spray"]))


def test_execute_rejects_expired_engagement() -> None:
    manifest = EngagementManifest.from_dict(
        base_manifest(valid_until_utc="2026-08-30T12:00:00Z")
    )
    runner = AuthorizedAssessmentRunner(manifest, sleeper=lambda _: None)
    with pytest.raises(EngagementError, match="expired"):
        runner.run(now=NOW)


def test_manifest_allows_omitted_engagement_id_and_derives_audit_id() -> None:
    data = base_manifest()
    data.pop("engagement_id")
    manifest = EngagementManifest.from_dict(data)
    report = dry_run_report(manifest)

    assert report["engagement_id"].startswith("auto-")
    assert report["engagement_id_source"] == "derived"


def test_manifest_allows_standing_authorization_without_validity_window() -> None:
    data = base_manifest()
    data.pop("valid_from_utc")
    data.pop("valid_until_utc")
    manifest = EngagementManifest.from_dict(data)

    manifest.validate(now=NOW, enforce_window=True)
    assert manifest.valid_from_utc == ""
    assert manifest.valid_until_utc == ""


def test_manifest_rejects_partial_validity_window() -> None:
    data = base_manifest()
    data.pop("valid_until_utc")
    with pytest.raises(EngagementError, match="must either both be set or both be omitted"):
        EngagementManifest.from_dict(data)


def test_request_budget_limits_generated_plan() -> None:
    manifest = EngagementManifest.from_dict(base_manifest(max_requests_per_target=2))
    plan = build_plan(manifest)
    assert len(plan) == 2
    assert [item.check for item in plan] == ["reachability", "root_snapshot"]


def test_dry_run_is_machine_readable_and_non_destructive() -> None:
    manifest = EngagementManifest.from_dict(base_manifest())
    report = dry_run_report(manifest)
    assert report["schema"] == "senju-authorized-assessment-plan/v1"
    assert report["destructive"] is False
    assert report["exact_hosts"] == ["example.com"]
    assert len(report["manifest_sha256"]) == 64
    assert len(report["plan"]) == 5


def test_runner_executes_through_guarded_transport_and_emits_evidence() -> None:
    seen: list[tuple[str, str]] = []

    def factory(policy):
        assert policy.allow_hosts == frozenset({"example.com"})
        assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
        assert policy.allow_delete is False

        def opener(req: urllib.request.Request, *, timeout: float):
            seen.append((req.get_method(), req.full_url))
            if req.full_url.endswith("/.well-known/security.txt"):
                return FakeResponse(200, b"Contact: mailto:security@example.com\n")
            if req.full_url.endswith("/robots.txt"):
                return FakeResponse(404, b"missing")
            if req.get_method() == "HEAD":
                return FakeResponse(200, b"")
            return FakeResponse(200, b"root")

        return ExternalContactClient(
            policy,
            resolver=lambda host, port: (PUBLIC_IP,),
            opener=opener,
            sleeper=lambda _: None,
        )

    manifest = EngagementManifest.from_dict(base_manifest())
    report = AuthorizedAssessmentRunner(
        manifest,
        client_factory=factory,
        sleeper=lambda _: None,
    ).run(now=NOW)

    assert report["schema"] == "senju-authorized-assessment/v1"
    assert report["request_count"] == 5
    assert report["destructive"] is False
    assert report["exact_hosts"] == ["example.com"]
    assert seen[0] == ("HEAD", "https://example.com/")
    assert seen[-1] == ("OPTIONS", "https://example.com/")

    observations = {item["check"]: item for item in report["observations"]}
    assert observations["security_txt"]["present"] is True
    assert observations["robots_txt"]["present"] is False
    assert observations["root_snapshot"]["body_captured"] is True
