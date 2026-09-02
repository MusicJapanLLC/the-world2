import pytest
from automation.control_plane.pr_traffic_controller import (
    calculate_overlap,
    classify_pr,
    generate_status_report,
    is_classification_valid,
    parse_objective_hints,
    route_next_agent,
    should_dispatch_ci,
)


def test_stale_sha_rejection():
    stored_entry = {
        "number": 101,
        "head_sha": "head_sha_v1",
        "observed_base_sha": "base_sha_v1",
        "classification": "READY",
    }
    current_pr_matching = {
        "number": 101,
        "head_sha": "head_sha_v1",
        "base_sha": "base_sha_v1",
    }
    current_pr_stale_head = {
        "number": 101,
        "head_sha": "head_sha_v2",
        "base_sha": "base_sha_v1",
    }
    current_pr_stale_base = {
        "number": 101,
        "head_sha": "head_sha_v1",
        "base_sha": "base_sha_v2",
    }

    assert is_classification_valid(stored_entry, current_pr_matching) is True
    assert is_classification_valid(stored_entry, current_pr_stale_head) is False
    assert is_classification_valid(stored_entry, current_pr_stale_base) is False

    previous_report = {
        "prs": [stored_entry]
    }
    updated_report = generate_status_report(
        prs=[current_pr_stale_head],
        repo_wide_blockers=[],
        previous_report=previous_report,
    )
    assert len(updated_report["prs"]) == 1
    assert updated_report["prs"][0]["valid"] is False
    assert any("Invalidated" in r for r in updated_report["prs"][0]["reasons"])


def test_deterministic_classification():
    pr_ready = {
        "number": 1,
        "title": "feat(world): clean feature",
        "head_sha": "h1",
        "base_sha": "b1",
        "changed_files": ["src/app.py"],
        "mergeable": True,
        "mergeable_state": "clean",
        "ci_status": "success",
    }
    res1 = classify_pr(pr_ready, repo_wide_blockers=[], all_open_prs=[pr_ready])
    res2 = classify_pr(pr_ready, repo_wide_blockers=[], all_open_prs=[pr_ready])
    assert res1["classification"] == "READY"
    assert res1 == res2

    pr_rebase = {
        "number": 2,
        "title": "fix: conflict",
        "head_sha": "h2",
        "base_sha": "b1",
        "changed_files": ["src/app.py"],
        "mergeable": False,
        "mergeable_state": "dirty",
    }
    assert classify_pr(pr_rebase, [], [pr_rebase])["classification"] == "REBASE"

    pr_repair = {
        "number": 3,
        "title": "fix: ci failure",
        "head_sha": "h3",
        "base_sha": "b1",
        "changed_files": ["src/app.py"],
        "mergeable": True,
        "ci_status": "failure",
    }
    assert classify_pr(pr_repair, [], [pr_repair])["classification"] == "REPAIR"


def test_overlap_detection():
    pr1 = {
        "number": 10,
        "title": "fix(world): resolve issue #218 in traffic control",
        "body": "Fixes #218 by updating traffic rules.",
        "changed_files": ["automation/control_plane/manager.py", "automation/control_plane/traffic.py"],
    }
    pr2 = {
        "number": 11,
        "title": "refactor(world): traffic control update for #218",
        "body": "Refactors traffic control rules.",
        "changed_files": ["automation/control_plane/manager.py", "automation/control_plane/boss_gate.py"],
    }

    hints1 = parse_objective_hints(pr1["title"], pr1["body"])
    assert "issue:218" in hints1
    assert "scope:world" in hints1

    overlapping, ratio, reasons = calculate_overlap(pr1, pr2)
    assert overlapping is True
    assert len(reasons) > 0

    # Overlapping PRs should be noted in classification
    res1 = classify_pr(pr1, repo_wide_blockers=[], all_open_prs=[pr1, pr2])
    assert 11 in res1["overlapping_prs"]


def test_superseded_classification():
    pr1 = {
        "number": 20,
        "title": "old fix",
        "body": "superseded by #21",
        "head_sha": "h20",
        "base_sha": "b1",
        "changed_files": ["src/old.py"],
    }
    res1 = classify_pr(pr1, repo_wide_blockers=[], all_open_prs=[pr1])
    assert res1["classification"] == "SUPERSEDED"


def test_repo_wide_blocker_priority():
    pr_feature_blocked = {
        "number": 30,
        "title": "feat: feature blocked",
        "body": "depends on #10",
        "head_sha": "h30",
        "base_sha": "b1",
        "changed_files": ["src/feature.py"],
        "feature_blockers": ["pr:#10"],
    }

    # When repo-wide blockers exist, repo-wide blocker priority takes precedence over feature blocker
    res_repo_blocked = classify_pr(
        pr_feature_blocked,
        repo_wide_blockers=["Security Gate CI Failing on Main"],
        all_open_prs=[pr_feature_blocked],
    )
    assert res_repo_blocked["classification"] == "BLOCKED"
    assert any("repo-wide: Security Gate CI Failing on Main" in b for b in res_repo_blocked["blockers"])


def test_next_agent_routing():
    pr_senju = {
        "number": 40,
        "title": "senju enhancement",
        "head_sha": "h40",
        "base_sha": "b1",
        "changed_files": ["senju/live_arena.py"],
    }
    assert route_next_agent(pr_senju, "READY", []) == "Senju-R&D"

    pr_foundry = {
        "number": 41,
        "title": "foundry update",
        "head_sha": "h41",
        "base_sha": "b1",
        "changed_files": ["ai_foundry/executor.py"],
    }
    assert route_next_agent(pr_foundry, "READY", []) == "FOUNDRY"

    pr_claude_governance = {
        "number": 42,
        "title": "update governance",
        "head_sha": "h42",
        "base_sha": "b1",
        "changed_files": ["SECURITY.md"],
    }
    assert route_next_agent(pr_claude_governance, "REVIEW", []) == "Claude-human"

    pr_openhands_complex = {
        "number": 43,
        "title": "major refactor",
        "head_sha": "h43",
        "base_sha": "b1",
        "changed_files": ["f1.py", "f2.py", "f3.py", "f4.py", "f5.py"],
    }
    assert route_next_agent(pr_openhands_complex, "REBASE", []) == "OpenHands"

    pr_jules = {
        "number": 44,
        "title": "simple fix",
        "head_sha": "h44",
        "base_sha": "b1",
        "changed_files": ["src/util.py"],
    }
    assert route_next_agent(pr_jules, "READY", []) == "Jules"


def test_should_dispatch_ci_suppression():
    # Security sensitive PRs must NEVER be suppressed
    assert should_dispatch_ci("SUPERSEDED", is_stale=True, is_security_sensitive=True) is True

    # Non-security SUPERSEDED PRs should suppress redundant CI dispatches
    assert should_dispatch_ci("SUPERSEDED", is_stale=False, is_security_sensitive=False) is False

    # Normal READY PRs should dispatch CI
    assert should_dispatch_ci("READY", is_stale=False, is_security_sensitive=False) is True
