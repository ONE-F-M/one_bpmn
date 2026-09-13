# Copyright (c) 2026, one-fm and contributors
"""The sandbox names its working branch after the Work Item, so the id has to
travel with every dispatch. It is resolved here from the A2A task rather than
asked of the model, because a model that sends it on some calls and not others
would split one work order across two branches.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops


class TestWorkItemIdFor(FrappeTestCase):
	def test_nothing_to_resolve_from_is_empty(self):
		self.assertEqual(ops.work_item_id_for(None), "")
		self.assertEqual(ops.work_item_id_for(""), "")

	def test_delegation_reference_wins(self):
		rows = frappe.get_all(
			"Agent Delegation",
			filters={"reference_doctype": "Work Item"},
			fields=["a2a_task", "reference_name"],
			limit=1,
		)
		if not rows:
			self.skipTest("no orchestrator-created delegation on this site")
		self.assertEqual(ops.work_item_id_for(rows[0].a2a_task), rows[0].reference_name)

	def test_falls_back_to_an_id_in_the_instruction(self):
		def get_value(doctype, *args, **kwargs):
			if doctype == "Agent Delegation":
				return None
			if doctype == "A2A Task":
				return '{"instruction": "Please fix WI-002322 today, not WI-000001 style."}'
			raise AssertionError(doctype)

		with patch.object(frappe.db, "get_value", side_effect=get_value):
			self.assertEqual(ops.work_item_id_for("A2A-x"), "WI-002322")

	def test_no_reference_and_no_id_in_text_is_empty(self):
		def get_value(doctype, *args, **kwargs):
			return None if doctype == "Agent Delegation" else '{"instruction": "Fix the thing."}'

		with patch.object(frappe.db, "get_value", side_effect=get_value):
			self.assertEqual(ops.work_item_id_for("A2A-x"), "")


class TestWorkItemIdReachesTheSandbox(FrappeTestCase):
	def _post_capture(self):
		sent = {}

		class _Response:
			def raise_for_status(self):
				return None

			def json(self):
				return {"ok": True}

		def post(url, json=None, headers=None, timeout=None):
			sent["url"] = url
			sent["json"] = json
			return _Response()

		return sent, post

	def test_fast_path_sends_the_resolved_id(self):
		sent, post = self._post_capture()
		with patch.object(ops, "_mint_identity_token", return_value="t"), patch.object(
			ops, "work_item_id_for", return_value="WI-002322"
		) as resolve, patch("requests.post", side_effect=post):
			result = ops.sandbox_dispatch("list_files", "one_bpmn", "staging", "Fix it.", {}, a2a_task="A2A-x")
		self.assertTrue(result["ok"])
		resolve.assert_called_once_with("A2A-x")
		self.assertTrue(sent["url"].endswith("/tool_call"))
		self.assertEqual(sent["json"]["work_item_id"], "WI-002322")

	def test_fast_path_without_a_task_sends_an_empty_id(self):
		sent, post = self._post_capture()
		with patch.object(ops, "_mint_identity_token", return_value="t"), patch("requests.post", side_effect=post):
			ops.sandbox_dispatch("list_files", "one_bpmn", "staging", "Fix it.", {})
		self.assertEqual(sent["json"]["work_item_id"], "")

	def test_slow_path_resolves_from_the_instance_context(self):
		sent, post = self._post_capture()
		instance = frappe._dict(name=None, context_doctype="A2A Task", context_docname="A2A-x")
		params = {"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "Fix it."}
		with patch.object(ops, "_mint_identity_token", return_value="t"), patch.object(
			ops, "work_item_id_for", return_value="WI-002322"
		) as resolve, patch("requests.post", side_effect=post):
			ops._dispatch_single_action(params, {"instance": instance, "task": None}, "run_tests")
		resolve.assert_called_once_with("A2A-x")
		self.assertTrue(sent["url"].endswith("/run"))
		self.assertEqual(sent["json"]["work_item_id"], "WI-002322")
		self.assertEqual(sent["json"]["action"], "run_tests")
