# Copyright (c) 2026, one-fm and contributors
"""The patch turns a hand-back that sets the orchestrator flag into one that clears it."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import hand_back_clears_the_orchestrator_flag as patch


class TestHandBackClearsTheOrchestratorFlagPatch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Server Script", patch.SCRIPT):
			self.skipTest(f"{patch.SCRIPT} is not on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _script(self) -> str:
		return frappe.db.get_value("Server Script", patch.SCRIPT, "script")

	def test_a_script_that_sets_the_flag_is_corrected(self):
		script = self._script().replace(patch.RIGHT, patch.WRONG)
		frappe.db.set_value("Server Script", patch.SCRIPT, "script", script)

		patch.execute()

		self.assertIn(patch.RIGHT, self._script())
		self.assertNotIn(patch.WRONG, self._script())

	def test_a_second_run_changes_nothing(self):
		patch.execute()
		once = self._script()

		patch.execute()

		self.assertEqual(self._script(), once)
