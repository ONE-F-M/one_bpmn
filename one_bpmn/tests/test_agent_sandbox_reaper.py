# Copyright (c) 2026, one-fm and contributors
"""A sandbox run that can no longer answer is settled, and the agent waiting on it is told why."""

from __future__ import annotations

import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.one_bpmn.connectors import agent_sandbox_reaper as reaper
from one_bpmn.one_bpmn.patches.v1_0 import settle_sandbox_runs_stuck_running as cleanup

ENQUEUE = "one_bpmn.api.agent_callback._enqueue_resume"


def _run(action="read_file", minutes_old=0, minutes_silent=None, caller=False, state="running") -> object:
	run = frappe.get_doc({
		"doctype": "Agent Sandbox Run", "state": state, "target_app": "one_bpmn", "action": action,
	})
	run.insert(ignore_permissions=True)
	started = add_to_date(now_datetime(), minutes=-minutes_old)
	updates = {"started_at": started}
	if minutes_silent is not None:
		updates["last_heartbeat"] = add_to_date(now_datetime(), minutes=-minutes_silent)
	if caller:
		updates["caller_wf_task_id"] = "task-1"
	run.db_set(updates, update_modified=False)
	return frappe.get_doc("Agent Sandbox Run", run.name)


class TestTheReaper(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _row(self, run):
		return frappe.db.get_value(
			"Agent Sandbox Run", run.name, ["state", "failure_class", "error_message", "completed_at", "resume_enqueued"],
			as_dict=True,
		)

	def test_a_fast_call_with_no_answer_for_five_minutes_goes_stale(self):
		run = _run("edit_file", minutes_old=6)
		with patch(ENQUEUE):
			self.assertTrue(reaper.settle_if_dead(run))
		row = self._row(run)
		self.assertEqual((row.state, row.failure_class), ("stale", "infra"))
		self.assertTrue(row.completed_at)
		self.assertIn("No answer for", row.error_message)

	def test_a_fast_call_inside_five_minutes_is_left_alone(self):
		run = _run("read_file", minutes_old=3)
		self.assertFalse(reaper.settle_if_dead(run))
		self.assertEqual(self._row(run).state, "running")

	def test_a_run_past_the_deadline_times_out_whatever_it_is(self):
		for action in ("read_file", "run_tests"):
			run = _run(action, minutes_old=46, minutes_silent=1)
			with patch(ENQUEUE):
				reaper.settle_if_dead(run)
			self.assertEqual(self._row(run).state, "timed_out", action)

	def test_a_slow_run_that_is_still_heard_from_is_left_alone(self):
		run = _run("run_tests", minutes_old=20, minutes_silent=2)
		with patch.object(reaper, "_sandbox_status") as status:
			self.assertFalse(reaper.settle_if_dead(run))
		status.assert_not_called()

	def test_a_silent_slow_run_the_sandbox_does_not_know_goes_stale(self):
		run = _run("run_tests", minutes_old=20, minutes_silent=12)
		with patch.object(reaper, "_sandbox_status", return_value=None), patch(ENQUEUE):
			self.assertTrue(reaper.settle_if_dead(run))
		row = self._row(run)
		self.assertEqual(row.state, "stale")
		self.assertIn("restarted", row.error_message)

	def test_a_silent_slow_run_the_sandbox_finished_goes_stale_naming_the_lost_callback(self):
		run = _run("open_pull_request", minutes_old=20, minutes_silent=12)
		with patch.object(reaper, "_sandbox_status", return_value={"state": "done"}), patch(ENQUEUE):
			reaper.settle_if_dead(run)
		self.assertIn("callback never arrived", self._row(run).error_message)

	def test_a_silent_slow_run_the_sandbox_still_reports_on_is_kept_and_its_heartbeat_recorded(self):
		run = _run("run_tests", minutes_old=20, minutes_silent=12)
		with patch.object(reaper, "_sandbox_status", return_value={"state": "running", "updated_at": time.time() - 30}):
			self.assertFalse(reaper.settle_if_dead(run))
		run.reload()
		self.assertEqual(run.state, "running")
		self.assertLess((now_datetime() - run.last_heartbeat).total_seconds(), 120)

	def test_a_sandbox_that_reports_nothing_recent_goes_stale(self):
		run = _run("run_tests", minutes_old=30, minutes_silent=12)
		old = {"state": "running", "updated_at": time.time() - 15 * 60}
		with patch.object(reaper, "_sandbox_status", return_value=old), patch(ENQUEUE):
			self.assertTrue(reaper.settle_if_dead(run))

	def test_the_waiting_agent_is_resumed_once(self):
		run = _run("run_tests", minutes_old=50, caller=True)
		with patch(ENQUEUE) as resume:
			reaper.settle_if_dead(run)
			run.reload()
			reaper.settle_if_dead(run)
		resume.assert_called_once()
		self.assertTrue(self._row(run).resume_enqueued)

	def test_a_run_nobody_waits_on_resumes_nobody(self):
		run = _run("edit_file", minutes_old=10)
		with patch(ENQUEUE) as resume:
			reaper.settle_if_dead(run)
		resume.assert_not_called()

	def test_a_finished_run_is_never_touched(self):
		run = _run("edit_file", minutes_old=600, state="completed")
		reaper.reap()
		self.assertEqual(self._row(run).state, "completed")

	def test_one_failing_run_does_not_stop_the_rest(self):
		bad = _run("read_file", minutes_old=10)
		good = _run("edit_file", minutes_old=10)
		original = reaper.settle_if_dead

		def flaky(run):
			if run.name == bad.name:
				raise RuntimeError("boom")
			return original(run)

		with patch.object(reaper, "settle_if_dead", side_effect=flaky), patch(ENQUEUE):
			reaper.reap()
		self.assertEqual(self._row(good).state, "stale")
		self.assertEqual(self._row(bad).state, "running")

	def test_the_cleanup_settles_old_runs_without_asking_the_sandbox(self):
		old = _run("run_tests", minutes_old=60 * 24 * 8, caller=True)
		young = _run("run_tests", minutes_old=20, minutes_silent=15)
		with patch.object(reaper, "_sandbox_status") as status, patch(ENQUEUE) as resume:
			cleanup.execute()
		status.assert_not_called()
		self.assertEqual(self._row(old).state, "timed_out")
		self.assertEqual(self._row(young).state, "running")
		resumed = [call.args[0].name for call in resume.call_args_list]
		self.assertIn(old.name, resumed)
		self.assertNotIn(young.name, resumed)


class TestTheSchedule(FrappeTestCase):
	def test_the_reaper_runs_every_two_minutes(self):
		from one_bpmn import hooks

		self.assertIn(
			"one_bpmn.one_bpmn.connectors.agent_sandbox_reaper.reap", hooks.scheduler_events["cron"]["*/2 * * * *"]
		)
