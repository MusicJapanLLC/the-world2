"""ScopeGuard の strict / experiment 挙動を検証する。"""
import pytest

import senju.safety as safety
from senju.safety import (
    ScopeGuard,
    ScopePolicy,
    ScopeViolation,
    default_lab_policy,
    experimental_lab_policy,
)


def test_simulated_targets_allowed():
    g = ScopeGuard(default_lab_policy())
    g.check("sim://web-1")


def test_authorized_public_lab_and_internal_urls_are_allowed():
    g = ScopeGuard(default_lab_policy())
    g.check("kabeya-authorized-test-range.onrender.com")
    g.check("https://kabeya-authorized-test-range.onrender.com/")
    g.check("https://kabeya-authorized-test-range.onrender.com/lab/index.html")
    g.check("https://kabeya-authorized-test-range.onrender.com/lab/nullharbor.html?role=admin#panel")


def test_authorization_does_not_leak_to_external_or_lookalike_hosts():
    g = ScopeGuard(default_lab_policy())
    for ref in (
        "https://example.com/",
        "https://kabeya-authorized-test-range.onrender.com.evil.example/",
        "https://evil-kabeya-authorized-test-range.onrender.com/",
    ):
        with pytest.raises(ScopeViolation):
            g.check(ref)


def test_public_ip_rejected_in_strict_mode():
    g = ScopeGuard(default_lab_policy())
    with pytest.raises(ScopeViolation):
        g.check("8.8.8.8")


def test_public_hostname_rejected_in_strict_mode():
    g = ScopeGuard(ScopePolicy(allow_private_network=True))
    with pytest.raises(ScopeViolation):
        g.check("example.com")


def test_private_ip_requires_optin_in_strict_mode():
    g = ScopeGuard(default_lab_policy())
    with pytest.raises(ScopeViolation):
        g.check("10.0.0.5")

    g2 = ScopeGuard(ScopePolicy(allow_private_network=True))
    g2.check("10.0.0.5")
    g2.check("127.0.0.1")


def test_violations_are_recorded():
    g = ScopeGuard(default_lab_policy())
    for ref in ("8.8.8.8", "external.example"):
        with pytest.raises(ScopeViolation):
            g.check(ref)
    assert len(g.violations) == 2


def test_labnet_requires_optin_in_strict_mode():
    g = ScopeGuard(default_lab_policy())
    with pytest.raises(ScopeViolation):
        g.check("labnet:dvwa")

    g2 = ScopeGuard(ScopePolicy(allow_private_network=True))
    g2.check("labnet:dvwa")


def test_experimental_mode_allows_abstract_external_refs_only_as_simulation_refs():
    g = ScopeGuard(experimental_lab_policy())
    g.check("example.com")
    g.check("203.0.113.10")
    g.check("research-target:anything")


def test_experimental_mode_allows_private_and_labnet_refs():
    g = ScopeGuard(experimental_lab_policy())
    g.check("10.0.0.5")
    g.check("127.0.0.1")
    g.check("labnet:juice-shop")


def test_empty_ref_still_rejected_in_experimental_mode():
    g = ScopeGuard(experimental_lab_policy())
    with pytest.raises(ScopeViolation):
        g.check("")


def test_no_unrestricted_noop_guard_is_exported():
    assert not hasattr(safety, "UnrestrictedArenaGuard")
    assert not hasattr(safety, "unrestricted_arena_guard")
