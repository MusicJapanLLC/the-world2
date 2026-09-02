import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from automation.world.realtime_kernel import (
    _latest_by_branch,
    _needs_head_revalidation,
    classify_run,
    collect,
)
from automation.world.core_director import validate_plan
from automation.world.self_heal_engine import _excerpt, _extract_source_locations, select_incident

NOW = datetime.now(timezone.utc)


class RealtimeKernelTests(unittest.TestCase):
    def test_classifies_running_failed_stale_and_healthy(self):
        base = {"id": 1, "run_attempt": 1}
        running = {**base, "status": "in_progress", "created_at": NOW.isoformat()}
        failed = {**base, "status": "completed", "conclusion": "failure", "updated_at": NOW.isoformat()}
        stale = {
            **base,
            "status": "completed",
            "conclusion": "success",
            "updated_at": (NOW - timedelta(minutes=61)).isoformat(),
        }
        healthy = {
            **base,
            "status": "completed",
            "conclusion": "success",
            "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        }
        self.assertEqual(classify_run(running, 60, NOW), "RUNNING")
        self.assertEqual(classify_run(failed, 60, NOW), "FAILED")
        self.assertEqual(classify_run(stale, 60, NOW), "STALE")
        self.assertEqual(classify_run(healthy, 60, NOW), "HEALTHY")

    def test_latest_by_branch_keeps_only_newest_run_and_ignores_repair_branches(self):
        runs = [
            {"id": 3, "head_branch": "feat/a"},
            {"id": 2, "head_branch": "feat/a"},
            {"id": 1, "head_branch": "the-world/self-heal-123"},
            {"id": 4, "head_branch": "feat/b"},
        ]
        latest = _latest_by_branch(runs)
        self.assertEqual(latest["feat/a"]["id"], 3)
        self.assertEqual(latest["feat/b"]["id"], 4)
        self.assertNotIn("the-world/self-heal-123", latest)

    def test_head_revalidation_only_when_run_sha_is_obsolete(self):
        run = {"head_sha": "old"}
        self.assertTrue(_needs_head_revalidation(run, "new"))
        self.assertFalse(_needs_head_revalidation(run, "old"))
        self.assertFalse(_needs_head_revalidation(run, ""))
        self.assertFalse(_needs_head_revalidation(None, "new"))

    @patch("automation.world.realtime_kernel._rerun_failed")
    @patch("automation.world.realtime_kernel._dispatch")
    @patch("automation.world.realtime_kernel._branch_head_sha", return_value="new-sha")
    @patch("automation.world.realtime_kernel._recent_runs")
    def test_kernel_revalidates_latest_head_before_rerun_or_repair(
        self, recent_runs, branch_head, dispatch, rerun_failed
    ):
        recent_runs.return_value = [
            {
                "id": 501,
                "head_branch": "main",
                "head_sha": "old-sha",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 3,
                "updated_at": NOW.isoformat(),
            }
        ]
        plan = {
            "default_ref": "main",
            "max_dispatches_per_pulse": 3,
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "repair_workflow": "",
            "workers": [
                {
                    "name": "SAFE",
                    "workflow": "safe.yml",
                    "stale_minutes": 60,
                    "priority": 10,
                    "autostart": True,
                    "recover_failures": True,
                }
            ],
        }
        pulse = collect(plan, apply_actions=True, ref="main")
        self.assertEqual(pulse["workers"][0]["action"], "REVALIDATE_HEAD")
        self.assertEqual(pulse["workers"][0]["action_result"], "REQUESTED")
        self.assertEqual(pulse["summary"]["head_revalidations"], 1)
        dispatch.assert_called_once_with("safe.yml", "main")
        rerun_failed.assert_not_called()
        branch_head.assert_called_once_with("main")

    @patch("automation.world.realtime_kernel._dispatch")
    @patch("automation.world.realtime_kernel._branch_head_sha", return_value="new-sha")
    @patch("automation.world.realtime_kernel._recent_runs")
    def test_required_current_head_revalidates_even_healthy_old_success(
        self, recent_runs, branch_head, dispatch
    ):
        recent_runs.return_value = [
            {
                "id": 601,
                "head_branch": "main",
                "head_sha": "old-sha",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "updated_at": NOW.isoformat(),
            }
        ]
        plan = {
            "default_ref": "main",
            "max_dispatches_per_pulse": 3,
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "repair_workflow": "",
            "workers": [
                {
                    "name": "SECURITY",
                    "workflow": "security.yml",
                    "stale_minutes": 480,
                    "priority": 10,
                    "autostart": True,
                    "recover_failures": True,
                    "require_current_head": True,
                }
            ],
        }
        pulse = collect(plan, apply_actions=True, ref="main")
        self.assertEqual(pulse["workers"][0]["state"], "HEALTHY")
        self.assertEqual(pulse["workers"][0]["action"], "REVALIDATE_REQUIRED_HEAD")
        self.assertEqual(pulse["workers"][0]["action_result"], "REQUESTED")
        self.assertEqual(pulse["summary"]["head_revalidations"], 1)
        dispatch.assert_called_once_with("security.yml", "main")
        branch_head.assert_called_once_with("main")

    @patch("automation.world.realtime_kernel._dispatch")
    @patch("automation.world.realtime_kernel._branch_head_sha", return_value="same-sha")
    @patch("automation.world.realtime_kernel._recent_runs")
    def test_required_current_head_does_nothing_when_success_is_current(
        self, recent_runs, branch_head, dispatch
    ):
        recent_runs.return_value = [
            {
                "id": 602,
                "head_branch": "main",
                "head_sha": "same-sha",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "updated_at": NOW.isoformat(),
            }
        ]
        plan = {
            "default_ref": "main",
            "max_dispatches_per_pulse": 3,
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "repair_workflow": "",
            "workers": [
                {
                    "name": "SECURITY",
                    "workflow": "security.yml",
                    "stale_minutes": 480,
                    "priority": 10,
                    "autostart": True,
                    "recover_failures": True,
                    "require_current_head": True,
                }
            ],
        }
        pulse = collect(plan, apply_actions=True, ref="main")
        self.assertEqual(pulse["workers"][0]["state"], "HEALTHY")
        self.assertEqual(pulse["workers"][0]["action"], "NONE")
        self.assertEqual(pulse["summary"]["head_revalidations"], 0)
        dispatch.assert_not_called()
        branch_head.assert_called_once_with("main")

    def test_director_rejects_fresh_and_non_allowlisted_actions(self):
        rt = {"workers": [{"workflow": "safe.yml", "stale_minutes": 60, "director_min_interval_minutes": 30}]}
        snap = {"workers": [{"workflow": "safe.yml", "state": "HEALTHY", "age_minutes": 10, "run_id": 1}]}
        plan = {
            "actions": [
                {"action": "dispatch", "workflow": "safe.yml", "reason": "too fresh"},
                {"action": "dispatch", "workflow": "evil.yml", "reason": "not allowlisted"},
            ]
        }
        self.assertEqual(validate_plan(plan, snap, rt), [])

    def test_director_accepts_stale_allowlisted_dispatch_once(self):
        rt = {"workers": [{"workflow": "safe.yml", "stale_minutes": 60, "director_min_interval_minutes": 30}]}
        snap = {"workers": [{"workflow": "safe.yml", "state": "STALE", "age_minutes": 80, "run_id": 1}]}
        plan = {
            "actions": [
                {"action": "dispatch", "workflow": "safe.yml", "reason": "restart"},
                {"action": "dispatch", "workflow": "safe.yml", "reason": "duplicate"},
            ]
        }
        accepted = validate_plan(plan, snap, rt)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["workflow"], "safe.yml")

    @patch("automation.world.self_heal_engine._branch_head_sha", return_value="abc")
    @patch("automation.world.self_heal_engine._recent_runs")
    def test_self_heal_selects_persistent_active_feature_failure(self, recent_runs, branch_head):
        recent_runs.return_value = [
            {
                "id": 99,
                "head_branch": "feat/world-test",
                "head_sha": "abc",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 2,
                "updated_at": NOW.isoformat(),
                "html_url": "https://github.com/example/run/99",
                "event": "pull_request",
            }
        ]
        plan = {
            "schema": "the-world-realtime-plan/v1",
            "default_ref": "main",
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "workers": [
                {
                    "name": "SAFE",
                    "workflow": "safe.yml",
                    "priority": 10,
                    "recover_failures": True,
                }
            ],
        }
        incident = select_incident(plan, now=NOW)
        self.assertIsNotNone(incident)
        self.assertEqual(incident["workflow"], "safe.yml")
        self.assertEqual(incident["head_branch"], "feat/world-test")
        self.assertEqual(incident["run_id"], 99)
        self.assertEqual(incident["current_branch_sha"], "abc")
        branch_head.assert_called_once_with("feat/world-test")

    @patch("automation.world.self_heal_engine._branch_head_sha", return_value="new-sha")
    @patch("automation.world.self_heal_engine._recent_runs")
    def test_self_heal_rejects_obsolete_failure_sha(self, recent_runs, branch_head):
        recent_runs.return_value = [
            {
                "id": 101,
                "head_branch": "feat/world-test",
                "head_sha": "old-sha",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 4,
                "updated_at": NOW.isoformat(),
            }
        ]
        plan = {
            "schema": "the-world-realtime-plan/v1",
            "default_ref": "main",
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "workers": [{"name": "SAFE", "workflow": "safe.yml", "priority": 10}],
        }
        self.assertIsNone(select_incident(plan, now=NOW))
        branch_head.assert_called_once_with("feat/world-test")

    @patch("automation.world.self_heal_engine._recent_runs")
    def test_self_heal_ignores_first_attempt_failure(self, recent_runs):
        recent_runs.return_value = [
            {
                "id": 100,
                "head_branch": "feat/world-test",
                "head_sha": "abc",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "updated_at": NOW.isoformat(),
            }
        ]
        plan = {
            "schema": "the-world-realtime-plan/v1",
            "default_ref": "main",
            "active_branch_window_minutes": 720,
            "repair_after_attempts": 2,
            "workers": [{"name": "SAFE", "workflow": "safe.yml", "priority": 10}],
        }
        self.assertIsNone(select_incident(plan, now=NOW))

    def test_repair_context_extracts_owned_traceback_and_pytest_locations(self):
        log = """
Traceback (most recent call last):
  File "/home/runner/work/test/test/automation/world/realtime_kernel.py", line 123, in collect
    boom()
senju/tests/test_evolution.py:44: AssertionError
/usr/lib/python3.12/json/__init__.py:20: ignored
"""
        locations = _extract_source_locations(log)
        self.assertIn(("automation/world/realtime_kernel.py", 123), locations)
        self.assertIn(("senju/tests/test_evolution.py", 44), locations)
        self.assertNotIn(("/usr/lib/python3.12/json/__init__.py", 20), locations)

    def test_excerpt_numbers_bounded_source_context(self):
        text = "\n".join(f"line-{i}" for i in range(1, 41))
        excerpt = _excerpt(text, 20, radius=2)
        self.assertEqual(excerpt["start_line"], 18)
        self.assertEqual(excerpt["end_line"], 22)
        self.assertIn("   20 | line-20", excerpt["text"])
        self.assertNotIn("line-17", excerpt["text"])


if __name__ == "__main__":
    unittest.main()
