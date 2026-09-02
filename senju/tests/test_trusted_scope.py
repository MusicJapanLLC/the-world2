from __future__ import annotations

from types import SimpleNamespace

import pytest

from senju.trusted_scope import (
    TrustedOwnerScope,
    TrustedRequest,
    TrustedScopeError,
    TrustedScopeRunner,
)


def test_trusted_scope_does_not_require_engagement_id_or_expiry() -> None:
    scope = TrustedOwnerScope.from_dict(
        {
            "domain_roots": ["example.com"],
            "effect_level": "state_change",
        }
    )
    assert scope.scope_id == "owner-default"
    assert scope.allows_url("https://api.example.com/health") is True
    assert scope.allows_url("https://deep.api.example.com/health") is True
    assert scope.allows_url("https://example.com/") is True


def test_trusted_scope_rejects_lookalike_domain() -> None:
    scope = TrustedOwnerScope.from_dict({"domain_roots": ["example.com"]})
    assert scope.allows_url("https://api.example.com/") is True
    assert scope.allows_url("https://example.com.evil.test/") is False
    assert scope.allows_url("https://evil-example.com/") is False


def test_state_change_methods_are_available_after_one_time_scope_enablement() -> None:
    scope = TrustedOwnerScope.from_dict(
        {
            "domain_roots": ["example.com"],
            "effect_level": "state_change",
            "allowed_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "max_redirects": 8,
            "max_rps": 10,
        }
    )
    policy = scope.policy_for_url("https://api.example.com/item/1", method="DELETE")
    assert policy.allow_hosts == frozenset({"api.example.com"})
    assert policy.allow_delete is True
    assert policy.follow_redirects is True
    assert policy.max_redirects == 8
    assert "DELETE" in policy.allowed_methods


def test_observe_scope_blocks_state_change() -> None:
    scope = TrustedOwnerScope.from_dict({"domain_roots": ["example.com"]})
    with pytest.raises(TrustedScopeError, match="effect_level=state_change"):
        scope.policy_for_url("https://api.example.com/item/1", method="POST")


def test_runner_executes_red_selected_subdomains_without_exact_host_manifest() -> None:
    scope = TrustedOwnerScope.from_dict(
        {
            "domain_roots": ["example.com"],
            "effect_level": "state_change",
            "max_rps": 20,
        }
    )

    seen_policies = []

    class FakeClient:
        def __init__(self, policy):
            seen_policies.append(policy)

        def contact_with_body(self, url, *, method, body=None, headers=None):
            host = url.split("/", 3)[2]
            receipt = SimpleNamespace(
                status=204,
                final_url=url,
                contacted_hosts=(host,),
                redirect_count=0,
                attempt_count=1,
                response_bytes=0,
                response_sha256="0" * 64,
                provider_acknowledged=True,
            )
            return SimpleNamespace(receipt=receipt, body=b"")

    runner = TrustedScopeRunner(scope, client_factory=FakeClient, sleeper=lambda _: None)
    report = runner.run(
        [
            TrustedRequest("https://api.example.com/a", "POST", "{}"),
            TrustedRequest("https://worker.example.com/b", "PATCH", "{}"),
        ]
    )

    assert report["engagement_id_required"] is False
    assert report["validity_window_required"] is False
    assert report["exact_host_manifest_required"] is False
    assert report["request_count"] == 2
    assert seen_policies[0].allow_hosts == frozenset({"api.example.com"})
    assert seen_policies[1].allow_hosts == frozenset({"worker.example.com"})


def test_unified_spear_entrypoint_is_available() -> None:
    from senju.spear import main as spear_main

    assert callable(spear_main)
