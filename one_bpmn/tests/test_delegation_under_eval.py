# Copyright (c) 2026, one-fm and contributors
"""A delegation made during an eval is recorded, not started.

The Orchestrator Baseline asserts on which specialist was chosen. Choosing one
for real runs a sandbox agent and can open a pull request, so under eval the
delegate tool stops before the A2A Task exists.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import a2a_client_ops as ops


class TestDelegationUnderEval(FrappeTestCase):
	def setUp(self):
		self._prev = getattr(frappe.flags, "eval_origin", None)

	def tearDown(self):
		frappe.flags.eval_origin = self._prev

	def _call(self):
		return ops.delegate_to_local_agent(
			{"agent": "Dev Agent", "instruction": "add a validation"},
			{"instance": None, "task": None},
		)

	def test_under_eval_nothing_is_started(self):
		frappe.flags.eval_origin = {"eval_case": "case-1", "eval_run": "run-1"}
		with patch.object(ops.local, "delegate") as delegate, patch.object(
			ops, "_work_item_refs", return_value={"work_item": None, "pull_request": None}
		):
			out = self._call()
		delegate.assert_not_called()
		self.assertEqual(out["state"], "not-started")
		self.assertEqual(out["reason"], "evaluation")
		self.assertIn("Dev Agent", out["text"])

	def test_outside_eval_the_delegation_goes_ahead(self):
		frappe.flags.eval_origin = None
		with patch.object(ops.local, "delegate", side_effect=RuntimeError("reached")) as delegate, patch.object(
			ops, "_work_item_refs", return_value={"work_item": None, "pull_request": None}
		), patch.object(ops, "_delegating_agent", return_value=None), patch.object(
			ops, "_parent_task", return_value=None
		):
			with self.assertRaises(RuntimeError):
				self._call()
		delegate.assert_called_once()
