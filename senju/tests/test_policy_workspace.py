import pytest

from senju.meta.policy_workspace import (
    EDITABLE_POLICY_DOMAINS,
    PRODUCTION_CANARY_KEY,
    edit_policy_workspace,
)


def test_all_requested_domains_are_fully_editable_in_sandbox():
    workspace = {domain: {"version": 1, "locked": True} for domain in EDITABLE_POLICY_DOMAINS}

    for domain in EDITABLE_POLICY_DOMAINS:
        result = edit_policy_workspace(
            workspace,
            domain,
            {"version": 2, "self_tuned": True},
            environment="sandbox",
        )
        assert result.applied is True
        assert result.proposal_only is False
        assert workspace[domain] == {"version": 2, "self_tuned": True}


def test_production_like_policy_changes_are_proposal_only_without_canary():
    for environment in ("production", "prod", "live", "real"):
        workspace = {"network_permission": {"egress": True}}
        result = edit_policy_workspace(
            workspace,
            "network permission",
            {"egress": False},
            environment=environment,
        )
        assert result.applied is False
        assert result.proposal_only is True
        assert workspace["network_permission"] == {"egress": True}
        assert result.requested == {"egress": False}


def test_production_canary_can_narrow_allowed_hosts_without_touching_global_policy():
    workspace = {"allowed_host": {"hosts": ["a.example", "b.example"]}}

    result = edit_policy_workspace(
        workspace,
        "allowed host",
        {"hosts": ["a.example"]},
        environment="production",
        canary_scope="meta-canary-1",
    )

    assert result.applied is True
    assert result.canary_applied is True
    assert result.proposal_only is False
    assert workspace["allowed_host"] == {"hosts": ["a.example", "b.example"]}
    assert workspace[PRODUCTION_CANARY_KEY]["meta-canary-1"]["allowed_host"] == {
        "hosts": ["a.example"]
    }


def test_production_canary_rejects_allowed_host_expansion():
    workspace = {"allowed_host": {"hosts": ["a.example"]}}

    with pytest.raises(PermissionError, match="may only narrow hosts"):
        edit_policy_workspace(
            workspace,
            "allowed host",
            {"hosts": ["a.example", "new.example"]},
            environment="live",
            canary_scope="meta-canary-1",
        )


def test_production_canary_can_reduce_network_permission():
    workspace = {
        "network_permission": {
            "egress": True,
            "ports": [443, 8443],
            "request_budget": 100,
        }
    }

    result = edit_policy_workspace(
        workspace,
        "network permission",
        {"egress": False, "ports": [443], "request_budget": 25},
        environment="real",
        canary_scope="meta-canary-1",
    )

    assert result.canary_applied is True
    assert workspace["network_permission"]["egress"] is True
    assert workspace[PRODUCTION_CANARY_KEY]["meta-canary-1"]["network_permission"] == {
        "egress": False,
        "ports": [443],
        "request_budget": 25,
    }


def test_production_canary_can_harden_merge_and_audit_requirements():
    workspace = {
        "merge_requirement": {
            "required": True,
            "approvals": 1,
            "checks": ["unit"],
        },
        "security_audit_requirement": {
            "required": False,
            "minimum_findings_reviewed": 1,
            "checks": ["secrets"],
        },
    }

    merge = edit_policy_workspace(
        workspace,
        "merge requirement",
        {"required": True, "approvals": 2, "checks": ["unit", "security"]},
        environment="production",
        canary_scope="meta-canary-1",
    )
    audit = edit_policy_workspace(
        workspace,
        "security audit requirement",
        {"required": True, "minimum_findings_reviewed": 2, "checks": ["secrets", "codeql"]},
        environment="production",
        canary_scope="meta-canary-1",
    )

    assert merge.canary_applied is True
    assert audit.canary_applied is True


def test_authority_stays_proposal_only_even_with_production_canary_scope():
    workspace = {"authority": {"role": "observer"}}
    result = edit_policy_workspace(
        workspace,
        "authority",
        {"role": "admin"},
        environment="production",
        canary_scope="meta-canary-1",
    )

    assert result.applied is False
    assert result.proposal_only is True
    assert result.canary_applied is False
    assert workspace["authority"] == {"role": "observer"}


def test_unknown_policy_domain_is_rejected():
    with pytest.raises(ValueError, match="unsupported Self-Tuner policy domain"):
        edit_policy_workspace({}, "unknown-policy", {}, environment="sandbox")
