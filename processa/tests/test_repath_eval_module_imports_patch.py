# Copyright (c) 2026, one-fm and contributors
"""The patch that points stored Server Script imports at the eval modules in ai_agent_evals."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import repath_eval_module_imports as P

SCRIPT_NAME = "ZZ Repath Eval Imports"
OLD_SCRIPT = "# processa.agents.eval_alerts.notify and processa.api.golden_dataset.export_dataset\nx = 1\n"
NEW_SCRIPT = (
	"# processa.ai_agent_evals.eval_alerts.notify and "
	"processa.ai_agent_evals.golden_dataset.export_dataset\nx = 1\n"
)


class TestRepathEvalModuleImports(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Server Script", {"name": SCRIPT_NAME})
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT_NAME,
				"script_type": "API",
				"api_method": "zz_repath_eval_imports",
				"script": OLD_SCRIPT,
			}
		).insert()

	def test_script_imports_move(self):
		P.execute()
		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT_NAME, "script"), NEW_SCRIPT)

	def test_running_twice_changes_nothing_more(self):
		P.execute()
		P.execute()
		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT_NAME, "script"), NEW_SCRIPT)
