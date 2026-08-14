# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001933: the outbound side — registry, client, delegation.

Nothing here touches the network: the transport is stubbed, so what is
under test is our own behaviour — approval enforcement, the SSRF guard,
outbound validation, the sync fast path, and parking.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.one_bpmn.connectors import a2a_client_ops
from one_bpmn.one_bpmn.integrations import a2a_client

CARD = {
	"protocolVersion": "0.3.0",
	"name": "Remote Helper",
	"description": "A remote agent",
	"url": "https://remote.example.com/rpc",
	"version": "1",
	"capabilities": {"streaming": False, "pushNotifications": False},
	"defaultInputModes": ["text/plain"],
	"defaultOutputModes": ["text/plain"],
	"skills": [{"id": "remote_helper", "name": "Help", "description": "Helps", "tags": ["help"]}],
}


def make_remote(approve=True, **kwargs):
	defaults = {
		"doctype": "A2A Remote Agent",
		"agent_name": f"_Test Remote {frappe.generate_hash(length=8)}",
		"endpoint_url": "https://remote.example.com/rpc",
		"enabled": 1,
		"approval_status": "Draft",
		"request_timeout": 5,
	}
	defaults.update(kwargs)
	remote = frappe.get_doc(defaults).insert(ignore_permissions=True)
	if approve:
		remote.db_set("agent_card", frappe.as_json(CARD), update_modified=False)
		remote.reload()
		remote.approval_status = "Approved"
		remote.save(ignore_permissions=True)
	return remote


def make_remote_for(agent, **kwargs):
	"""A registry entry whose card advertises one of our own agents — the
	loopback shape, and what lets the sub-agent allow-list name it."""
	card = {**CARD, "skills": [{**CARD["skills"][0], "id": agent.agent_id}]}
	remote = make_remote(approve=False, **kwargs)
	remote.db_set("agent_card", frappe.as_json(card), update_modified=False)
	remote.reload()
	remote.approval_status = "Approved"
	remote.save(ignore_permissions=True)
	return remote


def allow_test_host():
	"""The SSRF guard resolves hostnames for real, and the test endpoint is
	fictional. Tests that are ABOUT the guard use 127.0.0.1 (no DNS needed)
	and never patch it."""
	return patch.object(a2a_client, "_assert_host_allowed", lambda *a, **k: None)


def rpc_reply(result: dict):
	"""A stub requests-like response carrying a JSON-RPC result."""
	response = MagicMock()
	response.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": result}
	response.raise_for_status.return_value = None
	return response


def wire_task(state="working", task_id="remote-task-1", text=""):
	task = {"id": task_id, "kind": "task", "contextId": "ctx-1", "status": {"state": state}}
	if text:
		task["artifacts"] = [{"artifactId": "a1", "parts": [{"kind": "text", "text": text}]}]
	return task


class TestRemoteRegistry(FrappeTestCase):
	def test_approval_requires_a_card(self):
		remote = make_remote(approve=False)
		remote.approval_status = "Approved"
		self.assertRaises(frappe.ValidationError, remote.save)

	def test_endpoint_change_resets_approval(self):
		remote = make_remote()
		self.assertEqual(remote.approval_status, "Approved")
		remote.endpoint_url = "https://elsewhere.example.com/rpc"
		remote.save(ignore_permissions=True)
		self.assertEqual(remote.approval_status, "Draft")
		self.assertIsNone(remote.agent_card)

	def test_require_approved_rejects_draft_and_revoked(self):
		draft = make_remote(approve=False)
		with self.assertRaises(a2a_client.A2ANotApprovedError):
			a2a_client.require_approved(draft.name)

		revoked = make_remote()
		revoked.approval_status = "Revoked"
		revoked.save(ignore_permissions=True)
		with self.assertRaises(a2a_client.A2ANotApprovedError):
			a2a_client.require_approved(revoked.name)

	def test_choices_list_only_usable_entries(self):
		usable = make_remote()
		make_remote(approve=False)
		choices = a2a_client_ops.remote_agent_choices()
		self.assertIn(usable.name, choices)
		self.assertTrue(
			all(
				frappe.db.get_value("A2A Remote Agent", c, "approval_status") == "Approved"
				for c in choices
			)
		)

	def test_fetch_card_is_admin_only(self):
		remote = make_remote(approve=False)
		nobody = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"a2a-card-nobody-{frappe.generate_hash(length=6)}@example.com",
				"first_name": "Nobody",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		with self.set_user(nobody.name):
			self.assertRaises(frappe.PermissionError, remote.fetch_card)


class TestClientTransport(FrappeTestCase):
	def test_ssrf_guard_blocks_internal_hosts(self):
		remote = make_remote(endpoint_url="http://127.0.0.1:8000/rpc")
		with self.assertRaises(Exception) as caught:
			a2a_client.message_send(remote, "hello")
		self.assertIn("internal", str(caught.exception).lower())

	def test_internal_host_allowed_when_opted_in(self):
		remote = make_remote(endpoint_url="http://127.0.0.1:8000/rpc", allow_internal_hosts=1)
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task())
		with patch.object(a2a_client, "_session", return_value=session):
			result = a2a_client.message_send(remote, "hello")
		self.assertEqual(result["id"], "remote-task-1")

	def test_invalid_outbound_message_is_never_sent(self):
		remote = make_remote()
		session = MagicMock()
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			# An empty text list produces a message with no usable parts;
			# force the invalid shape through the validator.
			with patch(
				"one_bpmn.agents.a2a_contract.validate", return_value=["message: parts: too short"]
			):
				with self.assertRaises(a2a_client.A2AClientError):
					a2a_client.message_send(remote, "hello")
		session.post.assert_not_called()

	def test_remote_error_object_raises(self):
		remote = make_remote()
		response = MagicMock()
		response.json.return_value = {
			"jsonrpc": "2.0",
			"id": "1",
			"error": {"code": -32001, "message": "no such task"},
		}
		response.raise_for_status.return_value = None
		session = MagicMock()
		session.post.return_value = response
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			with self.assertRaises(a2a_client.A2ARemoteError) as caught:
				a2a_client.tasks_get(remote, "remote-task-1")
		self.assertEqual(caught.exception.code, -32001)

	def test_auth_header_is_sent(self):
		remote = make_remote(auth_scheme="Bearer")
		remote.credential = "s3cret"
		remote.save(ignore_permissions=True)
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task())
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			a2a_client.message_send(remote, "hello")
		headers = session.post.call_args.kwargs["headers"]
		self.assertEqual(headers["Authorization"], "Bearer s3cret")

	def test_text_extraction_from_task_and_message(self):
		self.assertEqual(
			a2a_client.remote_text(wire_task(state="completed", text="the answer")), "the answer"
		)
		self.assertEqual(
			a2a_client.remote_text({"kind": "message", "parts": [{"kind": "text", "text": "hi"}]}),
			"hi",
		)


class TestDelegateTask(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# The loopback shape: the remote's card advertises one of our own
		# agents, so the allow-list can name a real AI Agent Configuration.
		self.worker = make_agent_configuration()
		self.remote = make_remote_for(self.worker)
		self.orchestrator = make_agent_configuration()
		self.orchestrator.append("allowed_delegates", {"agent_configuration": self.worker.name})
		self.orchestrator.save(ignore_permissions=True)

	def _ctx(self):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-0000000000aa",
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_Delegate", name="ServiceTask_Delegate"),
		)
		instance = SimpleNamespace(name=None, initiated_by="Administrator", process_model=None)
		return {"instance": instance, "task": task}

	def _params(self, **kwargs):
		params = {
			"remote_agent": self.remote.name,
			"instruction": "please do the thing",
			"delegating_agent": self.orchestrator.name,
		}
		params.update(kwargs)
		return params

	def test_fast_reply_returns_inline_without_parking(self):
		ctx = self._ctx()
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task(state="completed", text="done already"))
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			result = a2a_client_ops.delegate_task(self._params(), ctx)
		self.assertEqual(result["state"], "completed")
		self.assertEqual(result["text"], "done already")
		self.assertNotIn(a2a_client_ops.A2A_WAITING_KEY, ctx["task"].data)
		row = frappe.get_doc("A2A Task", result["a2a_task"])
		self.assertEqual(row.direction, "Outbound")
		self.assertEqual(row.state, "completed")

	def test_slow_reply_parks_the_task(self):
		ctx = self._ctx()
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task(state="working"))
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			result = a2a_client_ops.delegate_task(self._params(), ctx)
		self.assertIsNone(result)
		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		self.assertEqual(marker["remote_task_id"], "remote-task-1")
		row = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertEqual(row.state, "working")
		self.assertTrue(row.deadline)
		self.assertTrue(row.next_poll_at)

	def test_unapproved_remote_cannot_be_delegated_to(self):
		draft = make_remote(approve=False)
		with self.assertRaises(a2a_client.A2ANotApprovedError):
			a2a_client_ops.delegate_task(self._params(remote_agent=draft.name), self._ctx())

	def test_delegation_off_the_sub_agent_list_is_refused(self):
		from one_bpmn.agents.a2a.guardrails import DelegationRefused

		stranger = make_remote_for(make_agent_configuration())
		with self.assertRaises(DelegationRefused):
			a2a_client_ops.delegate_task(self._params(remote_agent=stranger.name), self._ctx())

	def test_trace_metadata_travels_with_the_message(self):
		ctx = self._ctx()
		session = MagicMock()
		session.post.return_value = rpc_reply(wire_task(state="working"))
		with allow_test_host(), patch.object(a2a_client, "_session", return_value=session):
			a2a_client_ops.delegate_task(self._params(), ctx)
		sent = session.post.call_args.kwargs["json"]
		metadata = sent["params"]["message"]["metadata"]
		self.assertEqual(metadata["onefm_delegation_depth"], 1)
		self.assertEqual(metadata["onefm_handoff_count"], 1)

	def test_depth_limit_refuses_a_deep_chain(self):
		from one_bpmn.agents.a2a.guardrails import DelegationRefused

		self.orchestrator.max_recursion_depth = 1
		self.orchestrator.save(ignore_permissions=True)
		parent = frappe.get_doc(
			{
				"doctype": "A2A Task",
				"direction": "Outbound",
				"state": "working",
				"task_execution_id": f"exec-{frappe.generate_hash(length=6)}",
				"delegation_depth": 1,
				"handoff_count": 1,
			}
		)
		parent.flags.ignore_links = True
		parent.insert(ignore_permissions=True)

		with self.assertRaises(DelegationRefused) as caught:
			a2a_client_ops.delegate_task(self._params(parent_task=parent.name), self._ctx())
		self.assertEqual(caught.exception.reason_code, "max_recursion_depth")
