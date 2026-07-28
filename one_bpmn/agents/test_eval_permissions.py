"""WI-001744: tests for AI Evals permission scoping."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_permissions import (
	eval_case_query_conditions,
	eval_run_query_conditions,
	eval_suite_query_conditions,
)


class TestEvalPermissions(FrappeTestCase):
	def test_system_manager_is_unrestricted(self):
		"""System Manager gets an empty condition (sees everything)."""
		self.assertEqual(eval_suite_query_conditions("Administrator"), "")
		self.assertEqual(eval_case_query_conditions("Administrator"), "")
		self.assertEqual(eval_run_query_conditions("Administrator"), "")

	def test_non_manager_is_scoped_by_process_owner(self):
		"""A non-manager gets a condition tying the row to owned processes."""
		# A user with no System Manager role -> scoping applies.
		cond = eval_suite_query_conditions("nonexistent-user@example.com")
		self.assertIn("`tabAI Eval Suite`", cond)
		self.assertIn("process_owner", cond)

		self.assertIn("`tabAI Eval Case`.`suite`", eval_case_query_conditions("nonexistent-user@example.com"))
		self.assertIn("`tabAI Eval Run`.`suite`", eval_run_query_conditions("nonexistent-user@example.com"))
