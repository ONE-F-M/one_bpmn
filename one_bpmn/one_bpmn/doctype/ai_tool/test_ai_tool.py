# Copyright (c) 2026, Abdullah Almarzouq and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAITool(FrappeTestCase):
	def test_import_validation(self):
		# Verify that saving an invalid python path throws ValidationError
		doc = frappe.new_doc("AI Tool")
		doc.tool_name = "test_invalid_path"
		doc.python_path = "non_existent_module.non_existent_func"
		doc.description = "Test invalid path"
		self.assertRaises(frappe.ValidationError, doc.insert)

		# Verify that a valid path passes
		doc2 = frappe.new_doc("AI Tool")
		doc2.tool_name = "test_valid_path"
		doc2.python_path = "one_bpmn.one_bpmn.doctype.ai_tool.ai_tool.AITool"
		doc2.description = "Test valid path"
		doc2.insert()
		self.assertTrue(frappe.db.exists("AI Tool", "test_valid_path"))
		doc2.delete()
