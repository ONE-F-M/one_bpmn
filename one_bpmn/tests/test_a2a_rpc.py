# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001932: the A2A server door — envelope, gate, lifecycle.

The endpoint is exercised the way a real caller reaches it: a JSON-RPC
body on the request, authenticated as a client's service user. The
agent's actual turn is stubbed (like the AG-UI stream tests) — this
suite is about the door, not the model behind it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import a2a_contract
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api import a2a_api
from one_bpmn.tests.test_a2a_client_registry import approve, make_client


def make_exposed_agent(**kwargs):
	defaults = {"a2a_exposed": 1}
	defaults.update(kwargs)
	return make_agent_configuration(**defaults)


class RPCHarness(FrappeTestCase):
	"""Shared plumbing: fake the request body, call rpc(), read the reply."""

	def call_rpc(self, payload: dict, agent_id: str = None) -> dict:
		old_request = getattr(frappe.local, "request", None)
		old_response = frappe.local.response
		frappe.local.request = SimpleNamespace(data=frappe.as_json(payload).encode())
		frappe.local.response = frappe._dict()
		try:
			a2a_api.rpc(agent_id=agent_id)
			return dict(frappe.local.response)
		finally:
			frappe.local.request = old_request
			frappe.local.response = old_response

	def send(self, text: str, agent_id: str, task_id: str = None, request_id=1, metadata=None) -> dict:
		message = {"role": "user", "parts": [{"kind": "text", "text": text}], "kind": "message"}
		if task_id:
			message["taskId"] = task_id
		if metadata:
			message["metadata"] = metadata
		return self.call_rpc(
			{"jsonrpc": "2.0", "id": request_id, "method": "message/send", "params": {"message": message}},
			agent_id=agent_id,
		)

	def setup_pair(self):
		"""One exposed Live agent + one approved client allowed to call it."""
		agent = make_exposed_agent()
		client = approve(make_client(agents=[agent.name]))
		return agent, client


def stub_turn(response_text="stubbed reply", conversation=None):
	return patch(
		"one_bpmn.api.agent_invocation.invoke_agent",
		return_value={"response": response_text, "conversation": conversation},
	)


class TestA2AEnvelope(RPCHarness):
	def test_unparseable_body_is_parse_error(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			old = getattr(frappe.local, "request", None)
			frappe.local.request = SimpleNamespace(data=b"{not json")
			frappe.local.response = frappe._dict()
			try:
				a2a_api.rpc(agent_id=agent.agent_id)
				reply = dict(frappe.local.response)
			finally:
				frappe.local.request = old
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("PARSE_ERROR"))

	def test_invalid_envelope_is_rejected_and_logged(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			reply = self.call_rpc({"jsonrpc": "2.0", "id": 1}, agent_id=agent.agent_id)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("INVALID_REQUEST"))
		# WI-002009: the rejection is logged with which field failed, through
		# the same door every screening verdict uses.
		event = frappe.get_all(
			"AI Security Event",
			filters={"stage": "a2a-schema", "action": "Block", "detail": ("like", "%method%")},
			fields=["classifier", "boundary"],
			limit=1,
		)
		self.assertTrue(event, "schema rejection was not recorded as a security event")
		self.assertEqual(event[0].classifier, "jsonschema")
		self.assertEqual(event[0].boundary, "input")

	def test_http_status_is_always_200(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			reply = self.call_rpc({"jsonrpc": "2.0", "id": 1}, agent_id=agent.agent_id)
		self.assertEqual(reply["http_status_code"], 200)

	def test_unsupported_method(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			reply = self.call_rpc(
				{"jsonrpc": "2.0", "id": 5, "method": "message/stream", "params": {}},
				agent_id=agent.agent_id,
			)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("UNSUPPORTED_OPERATION"))
		self.assertEqual(reply["id"], 5)


class TestA2AGate(RPCHarness):
	def test_non_client_caller_is_refused(self):
		agent, _client = self.setup_pair()
		nobody = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"a2a-rpc-nobody-{frappe.generate_hash(length=8)}@example.com",
				"first_name": "Nobody",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		with self.set_user(nobody.name):
			reply = self.send("hello", agent.agent_id)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("INVALID_REQUEST"))

	def test_agent_off_allow_list_unexposed_and_unknown_look_identical(self):
		allowed = make_exposed_agent()
		off_list = make_exposed_agent()
		unexposed = make_agent_configuration()
		client = approve(make_client(agents=[allowed.name]))

		replies = []
		with self.set_user(client.user):
			for target in (off_list.agent_id, unexposed.agent_id, "no_such_agent"):
				replies.append(self.send("hello", target))
		messages = {json.dumps(r["error"], sort_keys=True) for r in replies}
		self.assertEqual(len(messages), 1)
		self.assertEqual(replies[0]["error"]["code"], a2a_contract.error_code("INVALID_PARAMS"))

	def test_draft_agent_is_refused_even_on_allow_list(self):
		agent = make_exposed_agent(lifecycle_status="Draft")
		client = approve(make_client(agents=[agent.name]))
		with self.set_user(client.user):
			reply = self.send("hello", agent.agent_id)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("INVALID_PARAMS"))


class TestA2AMessageSend(RPCHarness):
	def test_happy_turn_completes_with_artifact(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user), stub_turn("all done"):
			reply = self.send("do the thing", agent.agent_id)

		task = reply["result"]
		self.assertEqual(a2a_contract.validate("task", task), [])
		self.assertEqual(task["status"]["state"], "completed")
		self.assertEqual(task["artifacts"][0]["parts"][0]["text"], "all done")

		row = frappe.get_doc("A2A Task", {"task_id": task["id"]})
		self.assertEqual(row.direction, "Inbound")
		self.assertEqual(row.client, client.name)
		self.assertEqual(row.agent_configuration, agent.name)
		self.assertEqual(row.principal, client.user)

	def test_trace_metadata_lands_on_the_row(self):
		agent, client = self.setup_pair()
		metadata = {
			a2a_contract.trace_key("taskExecutionId"): "exec-123",
			a2a_contract.trace_key("delegationDepth"): 2,
			a2a_contract.trace_key("handoffCount"): 4,
		}
		with self.set_user(client.user), stub_turn():
			reply = self.send("counted", agent.agent_id, metadata=metadata)
		row = frappe.get_doc("A2A Task", {"task_id": reply["result"]["id"]})
		self.assertEqual(row.task_execution_id, "exec-123")
		self.assertEqual(row.delegation_depth, 2)
		self.assertEqual(row.handoff_count, 4)

	def test_non_text_part_is_rejected(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			reply = self.call_rpc(
				{
					"jsonrpc": "2.0",
					"id": 2,
					"method": "message/send",
					"params": {
						"message": {
							"role": "user",
							"parts": [{"kind": "data", "text": "{}"}],
						}
					},
				},
				agent_id=agent.agent_id,
			)
		self.assertEqual(
			reply["error"]["code"], a2a_contract.error_code("CONTENT_TYPE_NOT_SUPPORTED")
		)
		self.assertFalse(frappe.db.exists("A2A Task", {"client": client.name}))

	def test_failed_turn_returns_failed_task_not_error(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user), patch(
			"one_bpmn.api.agent_invocation.invoke_agent", side_effect=RuntimeError("boom")
		):
			reply = self.send("explode", agent.agent_id)
		self.assertEqual(reply["result"]["status"]["state"], "failed")


class TestA2ATasksGetAndCancel(RPCHarness):
	def _completed_task(self, agent, client, text="reply"):
		with stub_turn(text):
			reply = self.send("go", agent.agent_id)
		return reply["result"]["id"]

	def test_tasks_get_returns_own_task(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			task_id = self._completed_task(agent, client)
			reply = self.call_rpc(
				{"jsonrpc": "2.0", "id": 3, "method": "tasks/get", "params": {"id": task_id}},
				agent_id=agent.agent_id,
			)
		self.assertEqual(reply["result"]["status"]["state"], "completed")

	def test_foreign_task_is_not_found(self):
		agent, client = self.setup_pair()
		other_agent = make_exposed_agent()
		other_client = approve(make_client(agents=[other_agent.name]))
		with self.set_user(client.user):
			task_id = self._completed_task(agent, client)
		with self.set_user(other_client.user):
			reply = self.call_rpc(
				{"jsonrpc": "2.0", "id": 4, "method": "tasks/get", "params": {"id": task_id}},
				agent_id=other_agent.agent_id,
			)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("TASK_NOT_FOUND"))

	def test_cancel_submitted_task(self):
		agent, client = self.setup_pair()
		task = frappe.get_doc(
			{
				"doctype": "A2A Task",
				"direction": "Inbound",
				"state": "submitted",
				"client": client.name,
				"agent_configuration": agent.name,
				"principal": client.user,
			}
		).insert(ignore_permissions=True)
		with self.set_user(client.user):
			reply = self.call_rpc(
				{"jsonrpc": "2.0", "id": 6, "method": "tasks/cancel", "params": {"id": task.task_id}},
				agent_id=agent.agent_id,
			)
		self.assertEqual(reply["result"]["status"]["state"], "canceled")

	def test_completed_task_is_not_cancelable(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			task_id = self._completed_task(agent, client)
			reply = self.call_rpc(
				{"jsonrpc": "2.0", "id": 7, "method": "tasks/cancel", "params": {"id": task_id}},
				agent_id=agent.agent_id,
			)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("TASK_NOT_CANCELABLE"))


class TestA2AContinuation(RPCHarness):
	def test_continuation_screens_and_resumes(self):
		agent, client = self.setup_pair()
		task = frappe.get_doc(
			{
				"doctype": "A2A Task",
				"direction": "Inbound",
				"state": "input-required",
				"client": client.name,
				"agent_configuration": agent.name,
				"principal": client.user,
				"instance": "FAKE-INSTANCE",
				"pending_human_task": "aihuman::deadbeef01",
			}
		)
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)

		completed = MagicMock(return_value={"status": "ok"})
		with self.set_user(client.user), patch("one_bpmn.api.instance_api.complete_task", completed):
			reply = self.send("here is the answer", agent.agent_id, task_id=task.task_id)

		self.assertEqual(reply["result"]["status"]["state"], "working")
		completed.assert_called_once()
		args = completed.call_args[0]
		self.assertEqual(args[0], "FAKE-INSTANCE")
		self.assertEqual(args[1], "aihuman::deadbeef01")
		self.assertEqual(json.loads(args[2])["response"], "here is the answer")

	def test_continuing_a_task_not_waiting_is_refused(self):
		agent, client = self.setup_pair()
		with self.set_user(client.user):
			with stub_turn("done"):
				task_id = self.send("go", agent.agent_id)["result"]["id"]
			reply = self.send("more", agent.agent_id, task_id=task_id)
		self.assertEqual(reply["error"]["code"], a2a_contract.error_code("INVALID_PARAMS"))
