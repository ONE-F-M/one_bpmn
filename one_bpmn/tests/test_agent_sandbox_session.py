# Copyright (c) 2026, one-fm and contributors
"""A sandbox session: queued or started, registered once, fed commands, and closed."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.api import sandbox_session as api
from one_bpmn.one_bpmn.connectors import agent_sandbox_job as job
from one_bpmn.one_bpmn.connectors import agent_sandbox_session as sessions

SESSION_ARGS = {"work_item": "WI-SESS-1", "target_app": "one_bpmn", "git_branch": "staging", "agent_name": "Dev Agent", "caller_instance": None}
START = "one_bpmn.one_bpmn.connectors.agent_sandbox_job.start_execution"


class SessionCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		settings = SimpleNamespace(
			get=lambda field: {"sandbox_job_max_parallel": 2}.get(field),
			get_password=lambda *a, **k: "gh-token",
		)
		patcher = patch.object(frappe, "get_cached_doc", side_effect=self._cached(settings))
		patcher.start()
		self.addCleanup(patcher.stop)

	@staticmethod
	def _cached(settings):
		real = frappe.get_cached_doc

		def scoped(doctype, *args, **kwargs):
			return settings if doctype == "Processa Settings" else real(doctype, *args, **kwargs)

		return scoped

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _started(self, **overrides):
		"""A session whose Job has started, with the raw one-time token the container would receive."""
		with patch(START, return_value="projects/p/locations/l/jobs/j/executions/e1") as start:
			session = sessions.ensure_session(**{**SESSION_ARGS, **overrides})
		return session, start.call_args.args[1] if start.called else None

	def _registered(self, **overrides):
		session, token = self._started(**overrides)
		settings = sessions.register(session.name, token)
		return frappe.get_doc(sessions.SESSION, session.name), settings["session_key"]

	def _signed(self, body: dict, key: str, endpoint, signature=None):
		raw = json.dumps(body).encode()
		good = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
		with patch.object(frappe, "request", SimpleNamespace(get_data=lambda: raw)), patch.object(
			frappe, "get_request_header", lambda header: good if signature is None else signature
		):
			return endpoint()


class TestStartingASession(SessionCase):
	def test_a_new_session_starts_the_job_with_a_one_time_token(self):
		session, token = self._started()
		session.reload()
		self.assertEqual((session.state, session.attempt), ("starting", 1))
		self.assertEqual(session.execution_name, "projects/p/locations/l/jobs/j/executions/e1")
		self.assertEqual(session.register_token_hash, hashlib.sha256(token.encode()).hexdigest())
		self.assertNotEqual(session.register_token_hash, token)

	def test_a_second_call_for_the_same_work_item_reuses_the_live_session(self):
		first, _ = self._started()
		with patch(START) as start:
			second = sessions.ensure_session(**SESSION_ARGS)
		self.assertEqual(second.name, first.name)
		start.assert_not_called()

	def test_a_closed_session_is_followed_by_the_next_attempt(self):
		first, _ = self._started()
		first.db_set("state", "closed")
		second, _ = self._started()
		self.assertNotEqual(second.name, first.name)
		self.assertEqual(second.attempt, 2)

	def test_over_the_limit_a_session_waits_in_the_queue_without_starting_the_job(self):
		self._started(work_item="WI-A")
		self._started(work_item="WI-B")
		with patch(START) as start:
			third = sessions.ensure_session(**{**SESSION_ARGS, "work_item": "WI-C"})
		start.assert_not_called()
		self.assertEqual(third.state, "queued")

	def test_a_queued_session_starts_when_room_appears_oldest_first(self):
		a, _ = self._started(work_item="WI-A")
		self._started(work_item="WI-B")
		with patch(START) as nothing:
			c = sessions.ensure_session(**{**SESSION_ARGS, "work_item": "WI-C"})
			d = sessions.ensure_session(**{**SESSION_ARGS, "work_item": "WI-D"})
		nothing.assert_not_called()
		a.db_set("state", "closed")
		with patch(START, return_value="exec-c") as start:
			started = sessions.start_queued()
		self.assertEqual(started, 1)
		self.assertEqual(frappe.db.get_value(sessions.SESSION, c.name, "state"), "starting")
		self.assertEqual(frappe.db.get_value(sessions.SESSION, d.name, "state"), "queued")
		self.assertEqual(start.call_args.args[0], c.name)

	def test_a_job_that_cannot_start_loses_the_session_and_says_why(self):
		with patch(START, side_effect=job.SandboxJobError("quota")), self.assertRaises(job.SandboxJobError):
			sessions.ensure_session(**SESSION_ARGS)
		lost = frappe.get_all(sessions.SESSION, filters={"work_item": "WI-SESS-1"}, fields=["state", "error_message"])[0]
		self.assertEqual(lost.state, "lost")
		self.assertIn("quota", lost.error_message)

	def test_the_agent_flag_decides_whether_a_session_is_used(self):
		self.assertFalse(sessions.uses_job(None))
		self.assertFalse(sessions.uses_job("No Such Agent"))


class TestRegistering(SessionCase):
	def test_the_right_token_gives_the_settings_and_a_key_once(self):
		session, token = self._started()
		settings = sessions.register(session.name, token)
		self.assertEqual((settings["work_item"], settings["target_app"], settings["git_branch"]), ("WI-SESS-1", "one_bpmn", "staging"))
		self.assertEqual(settings["github_token"], "gh-token")
		self.assertTrue(settings["session_key"])
		session.reload()
		self.assertEqual((session.state, session.register_token_hash), ("registered", ""))
		self.assertIsNone(sessions.register(session.name, token))

	def test_a_wrong_token_unknown_session_or_empty_token_is_refused(self):
		session, token = self._started()
		self.assertIsNone(sessions.register(session.name, token + "x"))
		self.assertIsNone(sessions.register(session.name, ""))
		self.assertIsNone(sessions.register("no-such-session", token))
		self.assertEqual(frappe.db.get_value(sessions.SESSION, session.name, "state"), "starting")

	def test_a_token_used_after_its_window_is_refused(self):
		session, token = self._started()
		session.db_set("last_heartbeat", add_to_date(now_datetime(), seconds=-(sessions.REGISTER_WINDOW_SECONDS + 5)))
		self.assertIsNone(sessions.register(session.name, token))

	def test_the_endpoint_answers_opaquely_on_failure(self):
		session, token = self._started()
		out = self._signed({"session": session.name, "token": "bad"}, "k", api.register)
		self.assertEqual(out, {"accepted": False})
		ok = self._signed({"session": session.name, "token": token}, "k", api.register)
		self.assertTrue(ok["accepted"])
		self.assertTrue(ok["session_key"])


class TestThePollingEndpoints(SessionCase):
	def _command(self, session, **kwargs):
		return sessions.enqueue(session, kwargs.pop("kind", "tool"), kwargs.pop("action", "read_file"), kwargs.pop("payload", {"path": "a.py"}), **kwargs)

	def test_a_poll_with_nothing_pending_returns_no_command_and_marks_the_session_active(self):
		session, key = self._registered()
		out = self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)
		self.assertEqual(out, {"accepted": True, "command": None})
		self.assertEqual(frappe.db.get_value(sessions.SESSION, session.name, "state"), "active")

	def test_commands_are_handed_over_oldest_first_with_increasing_sequence_numbers(self):
		session, key = self._registered()
		first = self._command(session, payload={"path": "one"})
		second = self._command(session, payload={"path": "two"})
		self.assertEqual((first.seq, second.seq), (1, 2))
		got = [self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)["command"] for _ in range(2)]
		self.assertEqual([(c["seq"], c["payload"]["path"]) for c in got], [(1, "one"), (2, "two")])
		self.assertEqual(frappe.db.get_value(sessions.COMMAND, first.name, "state"), "delivered")

	def test_a_command_is_never_handed_over_twice(self):
		session, key = self._registered()
		self._command(session)
		self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)
		again = self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)
		self.assertIsNone(again["command"])

	def test_a_bad_signature_a_stale_timestamp_and_an_unregistered_session_are_refused(self):
		session, key = self._registered()
		body = {"session": session.name, "ts": time.time()}
		self.assertEqual(self._signed(body, key, api.next_command, signature="0" * 64), {"accepted": False})
		self.assertEqual(self._signed({**body, "ts": time.time() - 4000}, key, api.next_command), {"accepted": False})
		fresh, _token = self._started(work_item="WI-OTHER")
		self.assertEqual(self._signed({"session": fresh.name, "ts": time.time()}, key, api.next_command), {"accepted": False})

	def test_a_result_is_recorded_and_a_repeat_changes_nothing(self):
		session, key = self._registered()
		command = self._command(session)
		self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)
		body = {"session": session.name, "ts": time.time(), "seq": command.seq, "status": "ok", "result": {"content": "hi"}}
		self.assertEqual(self._signed(body, key, api.post_result), {"accepted": True})
		again = {**body, "result": {"content": "different"}}
		self.assertEqual(self._signed(again, key, api.post_result), {"accepted": True})
		row = frappe.db.get_value(sessions.COMMAND, command.name, ["state", "result"], as_dict=True)
		self.assertEqual((row.state, json.loads(row.result)), ("done", {"content": "hi"}))

	def test_an_error_result_marks_the_command_failed(self):
		session, key = self._registered()
		command = self._command(session)
		body = {"session": session.name, "ts": time.time(), "seq": command.seq, "status": "error", "result": {"error": "no such file"}}
		self._signed(body, key, api.post_result)
		self.assertEqual(frappe.db.get_value(sessions.COMMAND, command.name, "state"), "failed")

	def test_a_result_for_an_unknown_sequence_or_with_a_bad_shape_is_not_accepted(self):
		session, key = self._registered()
		base = {"session": session.name, "ts": time.time()}
		self.assertEqual(self._signed({**base, "seq": 99, "status": "ok", "result": {}}, key, api.post_result), {"accepted": False})
		for bad in ({"seq": "1", "status": "ok", "result": {}}, {"seq": 1, "status": "maybe", "result": {}}, {"seq": 1, "status": "ok", "result": "text"}):
			self.assertEqual(self._signed({**base, **bad}, key, api.post_result), {"accepted": False})

	def test_a_result_over_the_size_limit_fails_the_command_instead_of_filling_the_database(self):
		session, key = self._registered()
		command = self._command(session)
		huge = {"content": "x" * (sessions.MAX_RESULT_CHARS + 1)}
		self._signed({"session": session.name, "ts": time.time(), "seq": command.seq, "status": "ok", "result": huge}, key, api.post_result)
		row = frappe.db.get_value(sessions.COMMAND, command.name, ["state", "result"], as_dict=True)
		self.assertEqual(row.state, "failed")
		self.assertIn("over the", json.loads(row.result)["error"])

	def test_a_slow_result_settles_its_run_as_the_callback_would(self):
		session, key = self._registered()
		run = frappe.get_doc({"doctype": "Agent Sandbox Run", "state": "running", "target_app": "one_bpmn", "action": "run_tests"}).insert(ignore_permissions=True)
		command = self._command(session, kind="run_tests", action="run_tests", run=run.name)
		body = {"session": session.name, "ts": time.time(), "seq": command.seq, "status": "ok", "result": {"status": "tests_passed"}}
		with patch("one_bpmn.api.agent_callback.settle_as_agent") as settle:
			self._signed(body, key, api.post_result)
		settle.assert_called_once()
		self.assertEqual(settle.call_args.args[1], {"status": "tests_passed", "correlation_id": run.name})

	def test_the_close_result_closes_the_session(self):
		session, key = self._registered()
		sessions.close(session)
		self.assertEqual(frappe.db.get_value(sessions.SESSION, session.name, "state"), "closing")
		command = self._signed({"session": session.name, "ts": time.time()}, key, api.next_command)["command"]
		self.assertEqual(command["kind"], "close")
		self._signed({"session": session.name, "ts": time.time(), "seq": command["seq"], "status": "ok", "result": {}}, key, api.post_result)
		self.assertEqual(frappe.db.get_value(sessions.SESSION, session.name, "state"), "closed")


class TestQueueingACommand(SessionCase):
	def test_the_snapshot_ends_before_the_session_row_is_locked(self):
		session, _token = self._started()
		order = []
		frappe.db.commit.side_effect = lambda: order.append("commit")
		real_get_doc = frappe.get_doc

		def get_doc(*args, **kwargs):
			if kwargs.get("for_update"):
				order.append("lock")
			return real_get_doc(*args, **kwargs)

		with patch.object(frappe, "get_doc", side_effect=get_doc):
			sessions.enqueue(session, "tool", "list_files", {})
		self.assertEqual(order[:2], ["commit", "lock"])


class TestWaitingForAResult(SessionCase):
	def test_the_result_is_returned_once_the_container_has_written_it(self):
		session, _key = self._registered()
		command = sessions.enqueue(session, "tool", "read_file", {"path": "a.py"})

		def container_answers(_seconds):
			frappe.db.set_value(sessions.COMMAND, command.name, {"state": "done", "result": json.dumps({"content": "hi"})})

		self.assertEqual(sessions.wait_for(command, timeout=5, sleep=container_answers), {"ok": True, "content": "hi"})

	def test_a_failed_command_comes_back_not_ok_with_its_error(self):
		session, _key = self._registered()
		command = sessions.enqueue(session, "tool", "read_file", {})
		frappe.db.set_value(sessions.COMMAND, command.name, {"state": "failed", "result": json.dumps({"error": "boom"})})
		self.assertEqual(sessions.wait_for(command, timeout=5, sleep=lambda s: None), {"ok": False, "error": "boom"})

	def test_no_answer_in_time_gives_none(self):
		session, _key = self._registered()
		command = sessions.enqueue(session, "tool", "read_file", {})
		self.assertIsNone(sessions.wait_for(command, timeout=0.05, sleep=lambda s: time.sleep(0.02)))

	def test_a_session_that_is_lost_while_waiting_ends_the_wait_at_once(self):
		session, _key = self._registered()
		command = sessions.enqueue(session, "tool", "read_file", {})
		session.db_set("state", "lost")
		started = time.monotonic()
		self.assertIsNone(sessions.wait_for(command, timeout=30, sleep=lambda s: None))
		self.assertLess(time.monotonic() - started, 5)

	def test_the_wait_is_longer_while_the_container_is_still_starting(self):
		session, _token = self._started()
		self.assertEqual(sessions._timeout_for(session.name), sessions.START_WAIT_SECONDS)
		registered, _key = self._registered(work_item="WI-REG")
		self.assertEqual(sessions._timeout_for(registered.name), sessions.FAST_WAIT_SECONDS)


class TestHowLongACallWaitsForAStart(FrappeTestCase):
	def test_a_call_waits_at_least_as_long_as_a_container_may_take_to_register(self):
		self.assertGreaterEqual(sessions.START_WAIT_SECONDS, sessions.REGISTER_WINDOW_SECONDS)


class TestTheJobCalls(FrappeTestCase):
	def _settings(self, **fields):
		values = {"sandbox_job_project": "proj", "sandbox_job_region": "us-central1", "sandbox_job_name": "sbx", **fields}
		return SimpleNamespace(get=lambda f: values.get(f), get_password=lambda *a, **k: "{}")

	def test_the_job_is_run_with_the_session_id_token_and_processa_address(self):
		with patch.object(frappe, "get_cached_doc", return_value=self._settings()), patch.object(
			frappe.utils, "get_url", return_value="http://site.example"
		), patch.object(job, "_call", return_value={"metadata": {"name": "projects/p/executions/e9"}}) as call:
			name = job.start_execution("SESS-1", "tok-1")
		self.assertEqual(name, "projects/p/executions/e9")
		method, path, body = call.call_args.args
		self.assertEqual((method, path), ("POST", "/projects/proj/locations/us-central1/jobs/sbx:run"))
		env = {e["name"]: e["value"] for e in body["overrides"]["containerOverrides"][0]["env"]}
		self.assertEqual(env, {"SESSION_ID": "SESS-1", "SESSION_TOKEN": "tok-1", "PROCESSA_URL": "https://site.example"})

	def test_a_configured_address_wins_and_an_unnamed_execution_is_an_error(self):
		with patch.object(frappe, "get_cached_doc", return_value=self._settings(sandbox_job_processa_url="https://tunnel.example/")), patch.object(
			job, "_call", return_value={"metadata": {}}
		), self.assertRaises(job.SandboxJobError):
			job.start_execution("S", "t")
		self.assertEqual(job._processa_url.__name__, "_processa_url")

	def test_missing_job_settings_are_reported(self):
		with patch.object(frappe, "get_cached_doc", return_value=self._settings(sandbox_job_name="")), self.assertRaises(job.SandboxJobError):
			job.start_execution("S", "t")

	def test_cancel_and_status_address_the_execution(self):
		with patch.object(job, "_call", return_value={}) as call:
			job.cancel_execution("projects/p/executions/e1")
			job.execution_status("projects/p/executions/e1")
		self.assertEqual([c.args[:2] for c in call.call_args_list], [("POST", "/projects/p/executions/e1:cancel"), ("GET", "/projects/p/executions/e1")])
