from senju.domain_scope import (
    DomainHostSet,
    DomainScopeError,
    build_domain_scoped_policy,
    build_relaxed_domain_policy,
)


def test_domain_host_set_accepts_root_and_descendants() -> None:
    hosts = DomainHostSet(["owned.example.com"])
    assert "owned.example.com" in hosts
    assert "api.owned.example.com" in hosts
    assert "deep.api.owned.example.com" in hosts


def test_domain_host_set_rejects_suffix_confusion_and_other_domains() -> None:
    hosts = DomainHostSet(["owned.example.com"])
    assert "evil-owned.example.com" not in hosts
    assert "owned.example.com.attacker.example" not in hosts
    assert "unrelated.example.com" not in hosts


def test_level_five_relaxes_operational_budgets_not_target_boundary() -> None:
    policy = build_relaxed_domain_policy(["owned.example.com"], level=5)
    assert "api.owned.example.com" in policy.allow_hosts
    assert "unrelated.example.com" not in policy.allow_hosts
    assert policy.follow_redirects is True
    assert policy.max_redirects == 5
    assert policy.retries == 5
    assert policy.timeout_seconds == 20.0
    assert policy.max_response_bytes == 10 * 1024 * 1024
    assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
    assert policy.allow_delete is False


def test_expanded_methods_are_explicit() -> None:
    policy = build_relaxed_domain_policy(
        ["owned.example.com"],
        level=5,
        allowed_methods=("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"),
    )
    assert {"POST", "PUT", "PATCH"} <= policy.allowed_methods
    assert policy.allow_delete is False


def test_delete_still_requires_explicit_opt_in() -> None:
    try:
        build_domain_scoped_policy(["owned.example.com"], allowed_methods=("GET", "DELETE"))
    except DomainScopeError as exc:
        assert "DELETE" in str(exc)
    else:
        raise AssertionError("DELETE should require explicit opt-in")


def test_invalid_relaxation_level_is_rejected() -> None:
    try:
        build_relaxed_domain_policy(["owned.example.com"], level=6)
    except DomainScopeError as exc:
        assert "1 through 5" in str(exc)
    else:
        raise AssertionError("level 6 must be rejected")
