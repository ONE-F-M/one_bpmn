# Copyright (c) 2026, one-fm and contributors
"""The patch that points stored Server Script imports at the observability modules in ai_agent_observability."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import repath_observability_module_imports as P

SCRIPT_NAME = "ZZ Repath Observability Imports"
OLD_SCRIPT = (
	"# processa.agents.observability.record_tool_artifact and "
	"processa.api.insights_api.get_cost_allocation\nx = 1\n"
)
NEW_SCRIPT = (
	"# processa.ai_agent_observability.observability.record_tool_artifact and "
	"processa.api.insights.get_cost_allocation\nx = 1\n"
)


class TestRepathObservabilityModuleImports(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Server Script", {"name": SCRIPT_NAME})
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT_NAME,
				"script_type": "API",
				"api_method": "zz_repath_observability_imports",
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
