# Copyright (c) 2026, one-fm and contributors
"""The Bug Programmer loses its automatic test retry and no other agent does."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import bug_programmer_does_not_retry_its_reproduction_run as patch

FLAG = "sandbox_retry_on_test_failure"
OTHER = "Dev Agent"


class TestBugProgrammerRetryPatch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", patch.AGENT):
			self.skipTest(f"{patch.AGENT} is not on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_retry_is_switched_off_for_the_programmer_only(self):
		frappe.db.set_value("AI Agent Configuration", patch.AGENT, FLAG, 1)
		if frappe.db.exists("AI Agent Configuration", OTHER):
			frappe.db.set_value("AI Agent Configuration", OTHER, FLAG, 1)

		patch.execute()

		self.assertEqual(frappe.db.get_value("AI Agent Configuration", patch.AGENT, FLAG), 0)
		if frappe.db.exists("AI Agent Configuration", OTHER):
			self.assertEqual(frappe.db.get_value("AI Agent Configuration", OTHER, FLAG), 1)

	def test_a_second_run_changes_nothing(self):
		patch.execute()
		patch.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", patch.AGENT, FLAG), 0)
