# Copyright (c) 2026, one-fm and contributors
"""A site that only had the old dispatch operation gets run_tests and open_pull_request, and nothing it set is overwritten."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import (
	add_agent_sandbox_run_tests_and_pull_request_operations as operations_patch,
)

OPERATION = "BPMN Connector Operation"


def _name(operation_id: str) -> str | None:
	return frappe.db.get_value(
		OPERATION, {"connector": "agent_sandbox", "operation_id": operation_id}, "name"
	)


class TestAgentSandboxOperationsPatch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Connector", "agent_sandbox"):
			self.skipTest("no agent_sandbox connector on this site")
		for operation_id in ("run_tests", "open_pull_request"):
			if name := _name(operation_id):
				frappe.delete_doc(OPERATION, name, force=True, ignore_permissions=True)

	def test_both_operations_are_created_with_the_dispatch_handler(self):
		operations_patch.execute()
		for operation_id in ("run_tests", "open_pull_request"):
			doc = frappe.get_doc(OPERATION, _name(operation_id))
			self.assertEqual(doc.execution_type, "Python Handler")
			self.assertEqual(doc.handler_path, operations_patch.HANDLER)
			self.assertTrue(doc.enabled)

	def test_open_pull_request_asks_for_a_summary_and_run_tests_does_not(self):
		operations_patch.execute()
		fields = {
			operation_id: [row.field_name for row in frappe.get_doc(OPERATION, _name(operation_id)).fields]
			for operation_id in ("run_tests", "open_pull_request")
		}
		self.assertEqual(fields["run_tests"], ["target_app", "git_branch", "work_item_description"])
		self.assertEqual(fields["open_pull_request"][-1], "summary")

	def test_an_operation_a_site_already_configured_is_left_alone(self):
		operations_patch.execute()
		frappe.db.set_value(OPERATION, _name("run_tests"), "label", "Our own label")
		operations_patch.execute()
		self.assertEqual(frappe.db.get_value(OPERATION, _name("run_tests"), "label"), "Our own label")

	def test_a_site_without_the_connector_is_skipped(self):
		with patch.object(operations_patch.frappe.db, "exists", return_value=False):
			operations_patch.execute()
		self.assertIsNone(_name("run_tests"))
		self.assertIsNone(_name("open_pull_request"))
