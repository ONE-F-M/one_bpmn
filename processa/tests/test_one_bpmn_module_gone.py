# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The catch-all ONE BPMN module is gone and nothing new lands in it."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.docu import apply_doctype
from processa.patches.v1_0.delete_one_bpmn_module import execute


class TestOneBpmnModuleGone(FrappeTestCase):
	def test_modules_txt_lists_thirteen_modules_and_not_one_bpmn(self):
		with open(frappe.get_app_path("processa", "modules.txt")) as f:
			modules = [line.strip() for line in f if line.strip()]
		self.assertEqual(len(modules), 13)
		self.assertNotIn("ONE BPMN", modules)

	def test_the_patch_removes_the_module_def_and_leaves_no_doctype_in_it(self):
		execute()
		self.assertFalse(frappe.db.exists("Module Def", "ONE BPMN"))
		self.assertFalse(frappe.db.exists("DocType", {"module": "ONE BPMN"}))

	def test_a_design_naming_the_old_module_lands_in_processa_engine(self):
		execute()
		name = "Zz Gone Probe " + frappe.generate_hash(length=6).upper()
		ir = json.dumps(
			{
				"doctype_name": name,
				"module": "ONE BPMN",
				"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
			}
		)
		try:
			apply_doctype(ir, confirm=1)
			self.assertEqual(frappe.db.get_value("DocType", name, "module"), "Processa Engine")
		finally:
			if frappe.db.exists("DocType", name):
				frappe.delete_doc("DocType", name, force=True)
