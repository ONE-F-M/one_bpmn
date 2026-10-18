# Copyright (c) 2026, one-fm and contributors
"""The modify script reports the sub-process it changed, and the patch that adds that is safe to run twice."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_preview_opens_the_edited_subprocess as patch

NAME = "ProsAlly%Tool Modify Process"


class TestPreviewScopePatch(FrappeTestCase):
	def setUp(self):
		patch.execute()
		self.name = frappe.db.get_value("Server Script", {"name": ["like", NAME]}, "name")
		if not self.name:
			self.skipTest("the ProsAlly Modify Process script is not on this site")

	def test_the_modify_result_carries_the_sub_process_id(self):
		script = frappe.db.get_value("Server Script", self.name, "script")
		self.assertIn(patch.MARKER, script)

	def test_running_it_again_adds_the_key_once(self):
		patch.execute()
		script = frappe.db.get_value("Server Script", self.name, "script")
		self.assertEqual(script.count(patch.MARKER), 1)
