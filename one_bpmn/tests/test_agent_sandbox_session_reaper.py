# Copyright (c) 2026, one-fm and contributors
"""A session whose container never came, went silent or sat idle is handled, and the work waiting on it is told."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from one_bpmn.one_bpmn.connectors import agent_sandbox_job as job
from one_bpmn.one_bpmn.connectors import agent_sandbox_reaper as reaper
from one_bpmn.one_bpmn.connectors import agent_sandbox_session as sessions
from one_bpmn.tests.test_agent_sandbox_session import SessionCase


def _ago(seconds):
	return add_to_date(now_datetime(), seconds=-seconds)


class TestSessionReaper(SessionCase):
	def _session(self, state, silent_for, **fields):
		session, _token = self._started(work_item=f"WI-R-{state}-{silent_for}")
		session.db_set({"state": state, "last_heartbeat": _ago(silent_for), "registered_at": _ago(silent_for + 5), **fields})
		return frappe.get_doc(sessions.SESSION, session.name)

	def _state(self, session):
		return frappe.db.get_value(sessions.SESSION, session.name, ["state", "error_message"], as_dict=True)

	def test_a_container_that_never_registered_loses_the_session(self):
		session = self._session("starting", sessions.REGISTER_WINDOW_SECONDS + 10)
		with patch.object(job, "cancel_execution") as cancel:
			self.assertTrue(reaper.settle_session_if_dead(session))
		self.assertEqual(self._state(session).state, "lost")
		self.assertIn("never registered", self._state(session).error_message)
		cancel.assert_called_once()

	def test_a_container_still_inside_its_registration_window_is_left_alone(self):
		session = self._session("starting", 30)
		self.assertFalse(reaper.settle_session_if_dead(session))
		self.assertEqual(self._state(session).state, "starting")

	def test_a_silent_session_whose_container_exited_is_lost_with_that_reason(self):
		session = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		with patch.object(job, "execution_status", return_value={"completionTime": "2026-10-11T10:00:00Z"}), patch.object(job, "cancel_execution"):
			reaper.settle_session_if_dead(session)
		self.assertIn("exited", self._state(session).error_message)

	def test_a_silent_session_whose_container_still_runs_is_cancelled_and_lost(self):
		session = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		with patch.object(job, "execution_status", return_value={"runningCount": 1}), patch.object(job, "cancel_execution") as cancel:
			reaper.settle_session_if_dead(session)
		self.assertIn("stopped answering", self._state(session).error_message)
		cancel.assert_called_once_with("projects/p/locations/l/jobs/j/executions/e1")

	def test_when_cloud_run_cannot_be_asked_the_silent_session_is_still_lost(self):
		session = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		with patch.object(job, "execution_status", side_effect=job.SandboxJobError("403")), patch.object(job, "cancel_execution"):
			self.assertTrue(reaper.settle_session_if_dead(session))
		self.assertEqual(self._state(session).state, "lost")

	def test_a_failed_cancel_is_logged_and_does_not_stop_the_clean_up(self):
		session = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		with patch.object(job, "execution_status", return_value={}), patch.object(
			job, "cancel_execution", side_effect=job.SandboxJobError("gone")
		):
			self.assertTrue(reaper.settle_session_if_dead(session))
		self.assertEqual(self._state(session).state, "lost")

	def test_a_lost_session_fails_its_unanswered_commands_and_wakes_the_runs_waiting_on_them(self):
		session = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		run = frappe.get_doc({"doctype": "Agent Sandbox Run", "state": "running", "target_app": "one_bpmn", "action": "run_tests"}).insert(ignore_permissions=True)
		slow = sessions.enqueue(session, "run_tests", "run_tests", {}, run=run.name)
		fast = sessions.enqueue(session, "tool", "read_file", {})
		with patch.object(job, "execution_status", return_value={}), patch.object(job, "cancel_execution"), patch(
			"one_bpmn.api.agent_callback._enqueue_resume"
		):
			reaper.settle_session_if_dead(session)
		self.assertEqual(frappe.db.get_value(sessions.COMMAND, slow.name, "state"), "failed")
		self.assertEqual(frappe.db.get_value(sessions.COMMAND, fast.name, "state"), "failed")
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "state"), "stale")

	def test_a_session_that_is_alive_and_busy_is_left_alone(self):
		session = self._session("active", 20)
		sessions.enqueue(session, "tool", "read_file", {})
		self.assertFalse(reaper.settle_session_if_dead(session))
		self.assertEqual(self._state(session).state, "active")

	def test_an_idle_live_session_is_asked_to_close(self):
		session = self._session("active", 20, idle_timeout_seconds=60)
		command = sessions.enqueue(session, "tool", "read_file", {})
		frappe.db.set_value(sessions.COMMAND, command.name, "creation", _ago(300))
		reaper.settle_session_if_dead(session)
		self.assertEqual(self._state(session).state, "closing")
		self.assertTrue(frappe.db.exists(sessions.COMMAND, {"session": session.name, "kind": "close"}))

	def test_reaping_starts_the_queue_and_one_bad_session_does_not_stop_the_rest(self):
		bad = self._session("active", reaper.SESSION_SILENCE_SECONDS + 10)
		good = self._session("starting", sessions.REGISTER_WINDOW_SECONDS + 20)
		original = reaper.settle_session_if_dead

		def flaky(session):
			if session.name == bad.name:
				raise RuntimeError("boom")
			return original(session)

		with patch.object(sessions, "start_queued", return_value=0) as queue, patch.object(
			reaper, "settle_session_if_dead", side_effect=flaky
		), patch.object(job, "cancel_execution"):
			reaper.reap_sessions()
		queue.assert_called_once()
		self.assertEqual(self._state(good).state, "lost")
		self.assertEqual(self._state(bad).state, "active")

	def test_the_session_reaper_is_scheduled(self):
		from one_bpmn import hooks

		self.assertIn(
			"one_bpmn.one_bpmn.connectors.agent_sandbox_reaper.reap_sessions", hooks.scheduler_events["cron"]["*/2 * * * *"]
		)
