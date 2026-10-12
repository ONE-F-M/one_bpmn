# Copyright (c) 2026, one-fm and contributors
"""With an agent's Sandbox Use Job on, its tool calls and slow actions go to the Work Item's session, not the shared service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from one_bpmn.one_bpmn.connectors import agent_sandbox_job as job
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.connectors import agent_sandbox_session as sessions
from one_bpmn.tests.test_agent_sandbox_ops import AgentSandboxCase, _scoped_get_cached_doc

SETTINGS = SimpleNamespace(agent_sandbox_url="https://sandbox.example.run.app", get_password=lambda *a, **k: "gh-token")
SESSION = SimpleNamespace(name="SESS-1")


class RoutingCase(AgentSandboxCase):
	def setUp(self):
		super().setUp()
		patchers = [
			patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(SETTINGS)),
			patch.object(ops, "work_item_id_for", return_value="WI-R-1"),
			patch.object(ops, "_mint_identity_token", return_value="tok"),
		]
		for patcher in patchers:
			patcher.start()
			self.addCleanup(patcher.stop)
		self.session_on = patch.object(sessions, "uses_job", return_value=True)
		self.session_on.start()
		self.addCleanup(self.session_on.stop)

	def _last_run(self):
		return frappe.get_doc(
			"Agent Sandbox Run",
			frappe.get_all("Agent Sandbox Run", filters={"target_app": "one_bpmn"}, order_by="creation desc", pluck="name")[0],
		)


class TestAFastCallInASession(RoutingCase):
	def _call(self, answer, ensure=None):
		ensure = ensure or MagicMock(return_value=SESSION)
		with patch.object(sessions, "ensure_session", ensure), patch.object(
			sessions, "enqueue", return_value=SimpleNamespace(name="CMD-1", session="SESS-1")
		) as enqueue, patch.object(sessions, "wait_for", return_value=answer), patch("requests.post") as post:
			out = ops.sandbox_dispatch("read_file", "one_bpmn", "staging", "Fix it.", {"path": "a.py"}, "A2A-1", instance=SimpleNamespace(name=self._test_instance.name))
		return out, ensure, enqueue, post

	def test_the_call_is_queued_for_the_session_and_no_request_goes_to_the_service(self):
		out, ensure, enqueue, post = self._call({"ok": True, "found": True, "content": "hi"})
		post.assert_not_called()
		self.assertEqual(out, {"ok": True, "response": {"found": True, "content": "hi"}})
		self.assertEqual(enqueue.call_args.args[1:], ("tool", "read_file", {"args": {"path": "a.py"}}))
		self.assertEqual(ensure.call_args.kwargs["work_item"], "WI-R-1")
		self.assertEqual(ensure.call_args.kwargs["target_app"], "one_bpmn")

	def test_the_run_row_records_the_result_and_the_container_timings_not_shown_to_the_model(self):
		out, *_ = self._call({"ok": True, "content": "x", "timings_ms": {"tool": 4, "total": 9}})
		self.assertNotIn("timings_ms", out["response"])
		run = self._last_run()
		self.assertEqual((run.state, run.tool_ms, run.sandbox_ms), ("completed", 4, 9))
		self.assertTrue(run.completed_at)

	def test_a_command_that_failed_comes_back_as_the_tools_own_error(self):
		out, *_ = self._call({"ok": False, "error": "no such file"})
		self.assertEqual(out, {"ok": True, "response": {"error": "no such file"}})

	def test_no_answer_in_time_is_an_infrastructure_failure_the_model_is_told_about(self):
		out, *_ = self._call(None)
		self.assertFalse(out["ok"])
		self.assertIn("no answer in time", out["error"])
		run = self._last_run()
		self.assertEqual((run.state, run.failure_class), ("failed", "infra"))

	def test_a_job_that_cannot_start_is_reported_not_raised(self):
		out, *_ = self._call(None, ensure=MagicMock(side_effect=job.SandboxJobError("quota")))
		self.assertFalse(out["ok"])
		self.assertIn("quota", out["error"])
		self.assertEqual(self._last_run().state, "failed")


class TestTheServiceIsStillUsedOtherwise(RoutingCase):
	def _service(self, work_item="WI-R-1", flag=True):
		response = MagicMock(status_code=200)
		response.raise_for_status = MagicMock()
		response.headers = {}
		response.json = MagicMock(return_value={"found": True})
		with patch.object(sessions, "uses_job", return_value=flag), patch.object(ops, "work_item_id_for", return_value=work_item), patch.object(
			sessions, "ensure_session"
		) as ensure, patch("requests.post", return_value=response) as post:
			out = ops.sandbox_dispatch("read_file", "one_bpmn", "staging", "d", {"path": "a.py"}, "A2A-1", instance=SimpleNamespace(name=self._test_instance.name))
		return out, ensure, post

	def test_an_agent_without_the_flag_uses_the_service(self):
		out, ensure, post = self._service(flag=False)
		self.assertTrue(out["ok"])
		post.assert_called_once()
		ensure.assert_not_called()

	def test_a_call_with_no_work_item_uses_the_service_even_with_the_flag(self):
		out, ensure, post = self._service(work_item="")
		self.assertTrue(out["ok"])
		post.assert_called_once()
		ensure.assert_not_called()


class TestASlowActionInASession(RoutingCase):
	def _dispatch(self, operation, enqueue_error=None):
		ctx = self.ctx(operation=operation)
		with patch.object(sessions, "ensure_session", return_value=SESSION), patch.object(
			sessions, "enqueue", side_effect=enqueue_error, return_value=SimpleNamespace(name="CMD-1")
		) as enqueue, patch("requests.post") as post:
			try:
				result = ops.dispatch_action(
					{"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "d", "summary": "Did it."}, ctx
				)
			except ops.AgentSandboxError as exc:
				result = exc
		return result, ctx, enqueue, post

	def test_run_tests_is_queued_with_its_run_and_parks_the_step(self):
		result, ctx, enqueue, post = self._dispatch("run_tests")
		self.assertIsNone(result)
		post.assert_not_called()
		self.assertEqual(enqueue.call_args.args[1:3], ("run_tests", "run_tests"))
		run = self._last_run()
		self.assertEqual(enqueue.call_args.kwargs["run"], run.name)
		self.assertEqual(run.state, "running")
		self.assertEqual(ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]["run"], run.name)

	def test_the_pull_request_is_queued_as_a_finalize_command_with_the_summary(self):
		_result, _ctx, enqueue, _post = self._dispatch("open_pull_request")
		self.assertEqual(enqueue.call_args.args[1:3], ("finalize", "open_pull_request"))
		self.assertEqual(enqueue.call_args.args[3], {"args": {"summary": "Did it."}, "work_item_description": "d"})

	def test_a_queue_failure_fails_the_run_and_tells_the_agent(self):
		result, _ctx, _enqueue, _post = self._dispatch("run_tests", enqueue_error=RuntimeError("db down"))
		self.assertIsInstance(result, ops.AgentSandboxError)
		run = self._last_run()
		self.assertEqual((run.state, run.failure_class), ("failed", "infra"))
