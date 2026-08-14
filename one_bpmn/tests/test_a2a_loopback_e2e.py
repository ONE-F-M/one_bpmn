# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A loopback: our client side talking to our server side (WI-001931-4).

Building both halves means the whole protocol can be proven without an
external partner — and this is also the production shape for the
software-development epic, where the orchestrator delegates through the
client side to workers that receive through the server side.

The HTTP hop is short-circuited (the transport is replaced with a direct
call into our own rpc endpoint) so the test needs no running web server,
while everything either side of the wire is the real code: the card, the
client gate, the allow-list, the guardrails, the task rows, the state
mapping, parking and the poller.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn import tasks
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api import a2a_api
from one_bpmn.one_bpmn.connectors import a2a_client_ops
from one_bpmn.one_bpmn.integrations import a2a_client
from one_bpmn.tests.test_a2a_client_registry import approve, make_client


class LoopbackTransport:
	"""Replaces requests: a POST becomes a direct call into our own rpc
	endpoint, executed as the client's service user."""

	def __init__(self, agent_id: str, principal: str):
		self.agent_id = agent_id
		self.principal = principal
		self.sent: list[dict] = []

	def post(self, url, json=None, timeout=None, headers=None):
		self.sent.append(json)
		old_request = getattr(frappe.local, "request", None)
		old_response = frappe.local.response
		old_user = frappe.session.user
		frappe.local.request = SimpleNamespace(data=frappe.as_json(json).encode())
		frappe.local.response = frappe._dict()
		frappe.set_user(self.principal)
		try:
			a2a_api.rpc(agent_id=self.agent_id)
			payload = dict(frappe.local.response)
		finally:
			frappe.set_user(old_user)
			frappe.local.request = old_request
			frappe.local.response = old_response

		response = MagicMock()
		response.json.return_value = payload
		response.raise_for_status.return_value = None
		return response

	def get(self, *args, **kwargs):  # card fetches are not exercised here
		raise NotImplementedError


class TestA2ALoopback(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# The exposed worker — receives work through the server side.
		self.worker = make_agent_configuration(a2a_exposed=1, a2a_skill_tags="backend")
		# The orchestrator — delegates through the client side, and may only
		# delegate to the worker.
		self.orchestrator = make_agent_configuration()
		self.orchestrator.append("allowed_delegates", {"agent_configuration": self.worker.name})
		self.orchestrator.save(ignore_permissions=True)
		# We are our own approved caller, allowed to reach the worker.
		self.client = approve(make_client(agents=[self.worker.name]))
		# ...and our own registered remote, pointing at ourselves.
		self.remote = self._register_self()
		self.transport = LoopbackTransport(self.worker.agent_id, self.client.user)

	def _register_self(self):
		from one_bpmn.agents.a2a.card import build_agent_card

		remote = frappe.get_doc(
			{
				"doctype": "A2A Remote Agent",
				"agent_name": f"_Loopback {frappe.generate_hash(length=8)}",
				"endpoint_url": "http://127.0.0.1:8000/api/method/one_bpmn.api.a2a_api.rpc",
				"enabled": 1,
				"approval_status": "Draft",
				"allow_internal_hosts": 1,
				"poll_base_interval": 1,
				"poll_max_interval": 5,
				"default_task_timeout_minutes": 60,
			}
		).insert(ignore_permissions=True)
		# The card is the real one our own builder produces.
		card = build_agent_card(self.worker.agent_id)
		self.assertIsNotNone(card, "the worker should have a card — it is Live and exposed")
		remote.db_set("agent_card", frappe.as_json(card), update_modified=False)
		remote.reload()
		remote.approval_status = "Approved"
		remote.save(ignore_permissions=True)
		return remote

	def _ctx(self):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-00000000beef",
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_Delegate", name="ServiceTask_Delegate"),
		)
		instance = SimpleNamespace(name=None, initiated_by="Administrator", process_model=None)
		return {"instance": instance, "task": task}

	def _delegate(self, ctx, **params):
		merged = {
			"remote_agent": self.remote.name,
			"instruction": "add a field to the doctype",
			"delegating_agent": self.orchestrator.name,
		}
		merged.update(params)
		with patch.object(a2a_client, "_session", return_value=self.transport):
			return a2a_client_ops.delegate_task(merged, ctx)

	def test_full_round_trip_completes_inline(self):
		"""Delegate → the worker's turn runs → the answer comes back."""
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "field added", "conversation": None},
		):
			result = self._delegate(self._ctx())

		self.assertIsNotNone(result, "a completed remote should return inline, not park")
		self.assertEqual(result["state"], "completed")
		self.assertEqual(result["text"], "field added")

		# Both halves recorded their side of the same exchange.
		outbound = frappe.get_doc("A2A Task", result["a2a_task"])
		self.assertEqual(outbound.direction, "Outbound")
		self.assertEqual(outbound.state, "completed")
		self.assertTrue(outbound.remote_task_id)

		inbound = frappe.get_doc("A2A Task", {"task_id": outbound.remote_task_id})
		self.assertEqual(inbound.direction, "Inbound")
		self.assertEqual(inbound.state, "completed")
		self.assertEqual(inbound.client, self.client.name)
		self.assertEqual(inbound.agent_configuration, self.worker.name)
		self.assertEqual(inbound.principal, self.client.user)

		# The trace travelled with the message and was counted on arrival.
		self.assertEqual(inbound.delegation_depth, 1)
		self.assertEqual(inbound.handoff_count, 1)

	def test_the_wire_message_is_contract_valid(self):
		from one_bpmn.agents import a2a_contract

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "ok", "conversation": None},
		):
			self._delegate(self._ctx())
		envelope = self.transport.sent[0]
		self.assertEqual(a2a_contract.validate("rpc_request", envelope), [])
		self.assertEqual(a2a_contract.validate("message", envelope["params"]["message"]), [])

	def test_worker_failure_travels_back_as_a_failed_task(self):
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent", side_effect=RuntimeError("boom")
		):
			result = self._delegate(self._ctx())
		self.assertEqual(result["state"], "failed")
		self.assertEqual(frappe.get_doc("A2A Task", result["a2a_task"]).state, "failed")

	def test_delegation_to_an_agent_off_the_list_never_reaches_the_wire(self):
		from one_bpmn.agents.a2a.guardrails import DelegationRefused

		self.orchestrator.allowed_delegates = []
		self.orchestrator.save(ignore_permissions=True)
		with self.assertRaises(DelegationRefused):
			self._delegate(self._ctx())
		self.assertEqual(self.transport.sent, [], "nothing should have been sent")

	def test_caller_not_on_the_client_allow_list_is_refused_at_the_door(self):
		"""The server side refuses even though the client side approved:
		two independent gates, as intended."""
		self.client.allowed_agents = []
		self.client.save(ignore_permissions=True)
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "should not run", "conversation": None},
		) as turn:
			with self.assertRaises(a2a_client.A2ARemoteError):
				self._delegate(self._ctx())
		turn.assert_not_called()

	def test_parked_delegation_is_resumed_by_the_poller(self):
		"""The slow path: the worker is still working, so the Service Task
		parks; when the worker finishes, the poller wakes it."""
		# Force the server to answer "working" so the client parks.
		# Execution now lives in agents/a2a/execute, shared with the same-site
		# path — stub it there so the server answers "working" and we park.
		with patch(
			"one_bpmn.agents.a2a.execute.run_for_task", lambda task, config, text: None
		):
			ctx = self._ctx()
			result = self._delegate(ctx)

		self.assertIsNone(result, "a working remote should park")
		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		outbound = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertEqual(outbound.state, "submitted")

		# The worker finishes out of band.
		inbound = frappe.get_doc("A2A Task", {"task_id": outbound.remote_task_id})
		from one_bpmn.agents.a2a.task_store import store_result

		store_result(inbound, "finished later")

		# The poller sees it and wakes the parked process.
		frappe.db.set_value(
			"A2A Task", outbound.name, "next_poll_at", frappe.utils.add_to_date(
				frappe.utils.now_datetime(), seconds=-1
			), update_modified=False
		)
		woken = MagicMock()
		with patch.object(a2a_client, "_session", return_value=self.transport), patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			tasks.poll_a2a_tasks()

		outbound.reload()
		self.assertEqual(outbound.state, "completed")
		self.assertEqual(json.loads(outbound.result)["text"], "finished later")
		woken.assert_called_once()
