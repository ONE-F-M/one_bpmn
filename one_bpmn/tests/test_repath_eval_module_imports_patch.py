# Copyright (c) 2026, one-fm and contributors
"""The patch that points stored Server Script imports at the eval modules in ai_agent_evals."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_security.code_checks.script_gate import script_hash
from one_bpmn.one_bpmn.patches.v1_0 import repath_eval_module_imports as P

SCRIPT_NAME = "ZZ Repath Eval Imports"
OLD_SCRIPT = "# one_bpmn.agents.eval_alerts.notify and one_bpmn.api.golden_dataset.export_dataset\nx = 1\n"
NEW_SCRIPT = (
	"# one_bpmn.ai_agent_evals.eval_alerts.notify and "
	"one_bpmn.ai_agent_evals.golden_dataset.export_dataset\nx = 1\n"
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
		frappe.db.set_value(
			"Server Script",
			SCRIPT_NAME,
			{"processa_approved": 1, "processa_approved_hash": script_hash(OLD_SCRIPT)},
		)

	def test_script_imports_move_and_approval_follows(self):
		P.execute()
		row = frappe.db.get_value(
			"Server Script", SCRIPT_NAME, ["script", "processa_approved_hash"], as_dict=True
		)
		self.assertEqual(row.script, NEW_SCRIPT)
		self.assertEqual(row.processa_approved_hash, script_hash(NEW_SCRIPT))

	def test_running_twice_changes_nothing_more(self):
		P.execute()
		P.execute()
		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT_NAME, "script"), NEW_SCRIPT)

	def test_a_script_edited_since_approval_stays_unapproved(self):
		frappe.db.set_value("Server Script", SCRIPT_NAME, "processa_approved_hash", "stale")
		P.execute()
		row = frappe.db.get_value(
			"Server Script", SCRIPT_NAME, ["script", "processa_approved_hash"], as_dict=True
		)
		self.assertEqual(row.script, NEW_SCRIPT)
		self.assertEqual(row.processa_approved_hash, "stale")
