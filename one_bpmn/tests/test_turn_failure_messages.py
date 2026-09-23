# Copyright (c) 2026, one-fm and contributors

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.api import agent_invocation
from one_bpmn.api import server_script_api as SSA
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import BPMNProcessInstance

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]

CONVERSATION = "ZZ-TURN-FAILURE-CONV"


class TestTurnFailureMessages(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"tf-{frappe.generate_hash(length=6)}",
				"status": "Active",
				"context_doctype": "Chat Conversation",
				"context_docname": CONVERSATION,
			}
		)
		instance.flags.ignore_mandatory = True
		instance.flags.ignore_links = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.instance = instance.name
		self.turn_started = add_to_date(now_datetime(), seconds=-1)

	def _run(self, status, error_code=None, error_message=None, parent_run=None):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": self.instance,
				"bpmn_id": "Call_Agent",
				"status": status,
				"error_code": error_code,
				"error_message": error_message,
				"parent_run": parent_run,
				"started_at": now_datetime(),
			}
		).insert(ignore_permissions=True)

	def _message(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			SSA._raise_if_turn_failed(self.instance, self.turn_started)
		return str(ctx.exception)

	def test_turn_cap_shows_the_cap_message(self):
		self._run("Error", "TURN_CAP_REACHED", "Tool-calling loop hit the adapter's turn cap")
		self.assertIn("tool-call limit", self._message())

	def test_timeout_shows_the_timeout_message(self):
		self._run("Error", "TIMEOUT", "Model call exceeded aiTimeout (30s)")
		self.assertIn("timed out", self._message())

	def test_other_errors_show_their_code_and_escaped_message(self):
		self._run("Error", "FAILED_MODEL_CALL", "<b>401</b> invalid x-api-key")
		message = self._message()
		self.assertIn("FAILED_MODEL_CALL", message)
		self.assertIn("&lt;b&gt;401&lt;/b&gt;", message)

	def test_a_run_still_going_says_so(self):
		self._run("Running")
		self.assertIn("still working", self._message())

	def test_a_run_from_an_earlier_turn_is_ignored(self):
		self._run("Error", "TURN_CAP_REACHED")
		SSA._raise_if_turn_failed(self.instance, add_to_date(now_datetime(), seconds=5))

	def test_a_failed_child_run_under_a_good_turn_is_ignored(self):
		parent = self._run("Success")
		self._run("Error", "TIMEOUT", parent_run=parent.name)
		SSA._raise_if_turn_failed(self.instance, self.turn_started)

	def test_delegation_reports_the_failed_task_not_a_dead_process(self):
		def fail_the_turn(doc, *args, **kwargs):
			self._run("Error", "TURN_CAP_REACHED", "turn cap exhausted")
			frappe.throw("AI Agent Task 'Call_Agent' failed")

		with patch.object(BPMNProcessInstance, "receive_message", fail_the_turn):
			with self.assertRaises(frappe.ValidationError) as ctx:
				SSA._delegate_to_bpmn_instance(CONVERSATION, "hello", {})
		self.assertIn("tool-call limit", str(ctx.exception))

	def test_an_instance_that_is_not_waiting_still_returns_none(self):
		def not_waiting(doc, *args, **kwargs):
			frappe.throw("No task is waiting for this message")

		with patch.object(BPMNProcessInstance, "receive_message", not_waiting):
			self.assertIsNone(SSA._delegate_to_bpmn_instance(CONVERSATION, "hello", {}))

	def test_no_live_instance_logs_the_instance_state_then_says_reopen(self):
		with patch.object(frappe, "log_error") as log_error:
			with self.assertRaises(frappe.ValidationError) as ctx:
				agent_invocation._no_live_instance({"agent_id": "zz_agent"}, CONVERSATION)
		self.assertIn("reopen the chat", str(ctx.exception))
		kwargs = log_error.call_args.kwargs
		self.assertTrue(kwargs["defer_insert"])
		self.assertIn(self.instance, kwargs["message"])
		self.assertIn("Active", kwargs["message"])
