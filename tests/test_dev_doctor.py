import os
import pytest
from scripts.dev_doctor import (
    check_workflow_yamls,
    check_manifests_and_lockfiles,
    check_discoverable_commands,
    generate_report
)

def test_check_workflow_yamls(tmp_path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)

    wf1 = wf_dir / "wf1.yml"
    wf1.write_text("name: Test Workflow 1\non: push\njobs: {}\n")

    wf2 = wf_dir / "wf2.yml"
    wf2.write_text("name: Test Workflow 2\non: push\njobs:\n  step:\n    run: python scripts/non_existent.py\n")

    res = check_workflow_yamls(workflows_dir=str(wf_dir))
    assert res["files_checked"] == 2
    assert len(res["parse_errors"]) == 0
    assert len(res["missing_script_refs"]) == 1
    assert "wf2.yml references missing script 'scripts/non_existent.py'" in res["missing_script_refs"][0]

def test_check_manifests_and_lockfiles(tmp_path):
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"name": "test"}')

    res = check_manifests_and_lockfiles(repo_root=str(tmp_path))
    assert "package.json" in res["manifests_found"]
    assert len(res["lockfiles_found"]) == 0
    assert any("no lockfile" in w for w in res["warnings"])

def test_generate_report():
    report = generate_report()
    assert "# 🩺 Development Environment & Repository Health Audit Report" in report
    assert "Workflow YAML & Script Reference Audit" in report
