# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001933 follow-up: push notifications, both directions.

Push exists so a partner whose work runs for hours does not have to be
chased. It sits on top of polling and never replaces it, so the tests
care about two things in equal measure:

- the happy path — a callback wakes a parked delegation immediately;
- the endpoint's refusals — it is reachable without a session, so the
  per-task token is the whole gate, and every failure must look the same.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from one_bpmn import tasks as scheduled_tasks
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a import push
from one_bpmn.api import a2a_api
from one_bpmn.one_bpmn.connectors import a2a_client_ops
from one_bpmn.one_bpmn.integrations import a2a_client
from one_bpmn.tests.test_a2a_client import (
	CARD,
	allow_test_host,
	make_remote,
	make_remote_for,
	rpc_reply,
	wire_task,
)
from one_bpmn.tests.test_a2a_client_registry import approve, make_client

PUSHY_CARD = {**CARD, "capabilities": {"streaming": False, "pushNotifications": True}}


def make_pushy_remote(agent=None, **kwargs):
	"""A registry entry whose card advertises push support."""
	card = dict(PUSHY_CARD)
	if agent is not None:
		card["skills"] = [{**CARD["skills"][0], "id": agent.agent_id}]
	remote = make_remote(approve=False, **kwargs)
	remote.db_set("agent_card", frappe.as_json(card), update_modified=False)
	remote.reload()
	remote.approval_status = "Approved"
	remote.save(ignore_permissions=True)
	return remote


def make_outbound(remote, token=None, **kwargs):
	defaults = {
		"doctype": "A2A Task",
		"direction": "Outbound",
		"state": "working",
		"remote_agent": remote.name,
		"remote_task_id": "remote-task-1",
		"wf_task_id": "00000000-0000-0000-0000-0000000000aa",
		"push_registered": 1 if token else 0,
	}
	defaults.update(kwargs)
	task = frappe.get_doc(defaults)
	task.flags.ignore_links = True
	task.insert(ignore_permissions=True)
	if token:
		task.db_set("callback_token", token, update_modified=False)
		task.reload()
	return task


class CallbackHarness(FrappeTestCase):
	"""Calls the guest endpoint the way a remote would: a JSON body and a
	token header, with no session."""

	def post_callback(self, payload: dict, token: str | None) -> dict:
		old_request = getattr(frappe.local, "request", None)
		frappe.local.request = SimpleNamespace(
			data=frappe.as_json(payload).encode(),
			headers={push.TOKEN_HEADER: token} if token else {},
		)
		try:
			with patch(
				"frappe.get_request_header",
				side_effect=lambda name, default=None: token if name == push.TOKEN_HEADER else default,
			):
				return a2a_api.push_callback()
		finally:
			frappe.local.request = old_request


class TestPushCallbackGate(CallbackHarness):
	def test_correct_token_wakes_the_parked_delegation(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="s3cret-token")
		woken = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			result = self.post_callback(
				wire_task(state="completed", text="finished early"), "s3cret-token"
			)
		self.assertTrue(result["accepted"])
		task.reload()
		self.assertEqual(task.state, "completed")
		self.assertEqual(json.loads(task.result)["text"], "finished early")
		woken.assert_called_once()

	def test_wrong_token_changes_nothing(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="the-real-token")
		woken = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			result = self.post_callback(wire_task(state="completed", text="hijack"), "guessed")
		self.assertFalse(result["accepted"])
		task.reload()
		self.assertEqual(task.state, "working")
		woken.assert_not_called()

	def test_missing_token_changes_nothing(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="the-real-token")
		result = self.post_callback(wire_task(state="completed"), None)
		self.assertFalse(result["accepted"])
		task.reload()
		self.assertEqual(task.state, "working")

	def test_unknown_task_and_bad_token_are_indistinguishable(self):
		remote = make_pushy_remote()
		make_outbound(remote, token="the-real-token")
		bad_token = self.post_callback(wire_task(), "wrong")
		unknown_task = self.post_callback(
			wire_task(task_id="no-such-remote-task"), "the-real-token"
		)
		self.assertEqual(bad_token, unknown_task)

	def test_task_without_push_registered_is_not_reachable(self):
		remote = make_pushy_remote()
		task = make_outbound(remote)  # no token, push_registered = 0
		task.db_set("callback_token", "somehow", update_modified=False)
		result = self.post_callback(wire_task(state="completed"), "somehow")
		self.assertFalse(result["accepted"])

	def test_malformed_body_is_refused_quietly(self):
		old_request = getattr(frappe.local, "request", None)
		frappe.local.request = SimpleNamespace(data=b"{not json", headers={})
		try:
			self.assertFalse(a2a_api.push_callback()["accepted"])
		finally:
			frappe.local.request = old_request


class TestPushCallbackSemantics(CallbackHarness):
	def test_replay_after_terminal_is_a_no_op(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="tok", state="completed")
		woken = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			result = self.post_callback(wire_task(state="failed"), "tok")
		self.assertTrue(result["accepted"])
		task.reload()
		self.assertEqual(task.state, "completed", "a late callback must not rewrite history")
		woken.assert_not_called()

	def test_failure_callback_wakes_the_process(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="tok")
		woken = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			self.post_callback(wire_task(state="failed"), "tok")
		task.reload()
		self.assertEqual(task.state, "failed")
		woken.assert_called_once()

	def test_input_required_callback_asks_a_person(self):
		remote = make_pushy_remote()
		task = make_outbound(remote, token="tok", instance="FAKE-INSTANCE")
		asked = MagicMock()
		instance = MagicMock()
		instance._on_a2a_input_required = asked
		real_get_doc = frappe.get_doc

		def fake_get_doc(*args, **kwargs):
			if args and args[0] == "BPMN Process Instance":
				return instance
			return real_get_doc(*args, **kwargs)

		with patch("frappe.get_doc", side_effect=fake_get_doc):
			self.post_callback(
				{
					"id": "remote-task-1",
					"kind": "task",
					"status": {
						"state": "input-required",
						"message": {"role": "agent", "parts": [{"kind": "text", "text": "which branch?"}]},
					},
				},
				"tok",
			)
		task.reload()
		self.assertEqual(task.state, "input-required")
		asked.assert_called_once()


class TestOutboundRegistration(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.worker = make_agent_configuration(a2a_exposed=1)
		self.orchestrator = make_agent_configuration(restrict_delegates=1)
		self.orchestrator.append("allowed_delegates", {"agent_configuration": self.worker.name})
		self.orchestrator.save(ignore_permissions=True)

	def _delegate(self, remote, session):
		ctx = {
			"instance": SimpleNamespace(name=None, initiated_by="Administrator", process_model=None),
			"task": SimpleNamespace(
				id="00000000-0000-0000-0000-0000000000ff",
				data={},
				task_spec=SimpleNamespace(bpmn_id="ServiceTask_Delegate", name="ServiceTask_Delegate"),
			),
		}
		params = {
			"remote_agent": remote.name,
			"instruction": "long job please",
			"delegating_agent": self.orchestrator.name,
		}
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			a2a_client_ops.delegate_task(params, ctx)
		return ctx

	def test_registers_with_a_push_capable_remote_and_slows_polling(self):
		remote = make_pushy_remote(self.worker)
		session = MagicMock()
		session.post.side_effect = [
			rpc_reply(wire_task(state="working")),  # message/send
			rpc_reply({"taskId": "remote-task-1"}),  # pushNotificationConfig/set
		]
		ctx = self._delegate(remote, session)

		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		task = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertTrue(task.push_registered)
		self.assertTrue(task.get_password("callback_token", raise_exception=False))
		# Polling drops back to reconciliation rather than chasing.
		gap = (get_datetime(task.next_poll_at) - now_datetime()).total_seconds()
		self.assertGreater(gap, push.PUSH_RECONCILE_SECONDS - 120)

		registration = session.post.call_args_list[1].kwargs["json"]
		self.assertEqual(registration["method"], "tasks/pushNotificationConfig/set")
		self.assertIn("push_callback", registration["params"]["pushNotificationConfig"]["url"])

	def test_remote_without_push_is_left_on_polling(self):
		# Same allowed worker, but a card that does not advertise push.
		remote = make_remote_for(self.worker)
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task(state="working"))
		ctx = self._delegate(remote, session)

		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		task = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertFalse(task.push_registered)
		self.assertEqual(session.post.call_count, 1, "no registration call should be made")

	def test_failed_registration_falls_back_to_polling(self):
		remote = make_pushy_remote(self.worker)
		session = MagicMock()
		session.post.side_effect = [
			rpc_reply(wire_task(state="working")),
			RuntimeError("remote refused the config"),
		]
		ctx = self._delegate(remote, session)

		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		task = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertFalse(task.push_registered, "delegation must survive a declined registration")
		self.assertEqual(task.state, "working")


class TestInboundNotification(FrappeTestCase):
	def make_inbound(self, **kwargs):
		agent = make_agent_configuration(a2a_exposed=1)
		client = approve(make_client(agents=[agent.name]))
		defaults = {
			"doctype": "A2A Task",
			"direction": "Inbound",
			"state": "working",
			"client": client.name,
			"agent_configuration": agent.name,
			"principal": client.user,
		}
		defaults.update(kwargs)
		task = frappe.get_doc(defaults)
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)
		return task

	def test_caller_config_is_stored_and_ssrf_checked(self):
		task = self.make_inbound()
		with patch("one_bpmn.one_bpmn.connectors.http_ops._assert_host_allowed") as guard:
			push.store_caller_config(
				task, {"url": "https://caller.example.com/hook", "token": "caller-token"}
			)
		guard.assert_called_once()
		task.reload()
		self.assertEqual(task.push_callback_url, "https://caller.example.com/hook")
		self.assertEqual(task.get_password("push_callback_token", raise_exception=False), "caller-token")

	def test_internal_callback_url_is_refused(self):
		task = self.make_inbound()
		with self.assertRaises(Exception) as caught:
			push.store_caller_config(task, {"url": "http://127.0.0.1:8000/hook"})
		self.assertIn("internal", str(caught.exception).lower())

	def test_config_without_url_is_rejected_by_schema(self):
		from one_bpmn.agents.a2a.protocol import A2AError

		task = self.make_inbound()
		with self.assertRaises(A2AError):
			push.store_caller_config(task, {"token": "only-a-token"})

	def test_terminal_state_posts_to_the_caller(self):
		task = self.make_inbound(
			push_callback_url="https://caller.example.com/hook", state="completed"
		)
		session = MagicMock()
		session.post.return_value = MagicMock(raise_for_status=MagicMock())
		with patch("one_bpmn.one_bpmn.connectors.http_ops._assert_host_allowed"), patch.object(
			a2a_client, "_session", return_value=session
		):
			push.notify_caller(task)
		session.post.assert_called_once()
		self.assertEqual(session.post.call_args.args[0], "https://caller.example.com/hook")

	def test_working_state_is_not_pushed(self):
		task = self.make_inbound(push_callback_url="https://caller.example.com/hook")
		session = MagicMock()
		with patch.object(a2a_client, "_session", return_value=session):
			push.notify_caller(task)
		session.post.assert_not_called()

	def test_delivery_failure_is_counted_and_never_raises(self):
		task = self.make_inbound(
			push_callback_url="https://caller.example.com/hook", state="completed"
		)
		session = MagicMock()
		session.post.side_effect = RuntimeError("caller is down")
		with patch("one_bpmn.one_bpmn.connectors.http_ops._assert_host_allowed"), patch.object(
			a2a_client, "_session", return_value=session
		):
			push.notify_caller(task)  # must not raise
		task.reload()
		self.assertEqual(task.push_failures, 1)

	def test_delivery_stops_after_repeated_failures(self):
		task = self.make_inbound(
			push_callback_url="https://caller.example.com/hook",
			state="completed",
			push_failures=push.MAX_PUSH_FAILURES,
		)
		session = MagicMock()
		with patch.object(a2a_client, "_session", return_value=session):
			push.notify_caller(task)
		session.post.assert_not_called()


class TestPollerWithPush(FrappeTestCase):
	def tearDown(self):
		for name in self.made:
			frappe.delete_doc("A2A Task", name, force=True, ignore_permissions=True, ignore_missing=True)
		for name in self.remotes:
			frappe.delete_doc(
				"A2A Remote Agent", name, force=True, ignore_permissions=True, ignore_missing=True
			)
		frappe.db.commit()
		super().tearDown()

	def setUp(self):
		super().setUp()
		self.made = []
		self.remotes = []

	def test_push_registered_task_is_reconciled_not_chased(self):
		remote = make_pushy_remote()
		self.remotes.append(remote.name)
		task = make_outbound(
			remote, token="tok", next_poll_at=add_to_date(now_datetime(), seconds=-1)
		)
		self.made.append(task.name)

		with patch.multiple(
			a2a_client,
			tasks_get=MagicMock(return_value=wire_task()),
			tasks_cancel=MagicMock(),
		), patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			MagicMock(),
		):
			scheduled_tasks.poll_a2a_tasks()

		task.reload()
		gap = (get_datetime(task.next_poll_at) - now_datetime()).total_seconds()
		self.assertGreater(
			gap,
			push.PUSH_RECONCILE_SECONDS - 120,
			"a pushing remote should be reconciled on a long interval, not polled on backoff",
		)
