import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.cutover import patch_line, rename_app

OLD_LINES = {
	"one_bpmn.one_bpmn.patches.v1_0.move_agent_chat_doctypes_to_one_bpmn #16-07-2026": "processa.patches.v1_0.move_agent_chat_doctypes_to_processa #16-07-2026",
	"one_bpmn.one_bpmn.patches.v1_0.delete_one_bpmn_module #11-11-2026 the ONE BPMN module is gone; records still in it move to Processa Engine": "processa.patches.v1_0.delete_one_bpmn_module #11-11-2026 the ONE BPMN module is gone; records still in it move to Processa Engine",
	"one_bpmn.one_bpmn.patches.v1_0.repath_a2a_handlers #08-11-2026 stored A2A connector handler and Choices From paths follow a2a_client_ops into one_bpmn.a2a.client_ops": "processa.patches.v1_0.repath_a2a_handlers #08-11-2026 stored A2A connector handler and Choices From paths follow a2a_client_ops into processa.a2a.client_ops",
}


class TestCutover(FrappeTestCase):
	def test_patch_line_gives_the_current_patches_txt_line(self):
		lines = set(open(frappe.get_app_path("processa", "patches.txt")).read().splitlines())
		for old, new in OLD_LINES.items():
			self.assertEqual(patch_line(old), new)
			self.assertIn(new, lines)

	def test_rename_app_moves_site_records_once(self):
		module = frappe.get_doc({"doctype": "Module Def", "module_name": "Cutover Probe", "app_name": "one_bpmn"})
		module.db_insert()
		old = next(iter(OLD_LINES))
		frappe.db.delete("Patch Log", {"patch": OLD_LINES[old]})
		patch_log = frappe.get_doc({"doctype": "Patch Log", "patch": old}).insert()
		installed = json.loads(frappe.db.get_global("installed_apps"))
		frappe.db.set_global("installed_apps", json.dumps(["one_bpmn" if app == "processa" else app for app in installed]))

		rename_app()
		rename_app()

		self.assertEqual(json.loads(frappe.db.get_global("installed_apps")), installed)
		self.assertEqual(frappe.db.get_value("Module Def", module.name, "app_name"), "processa")
		self.assertEqual(frappe.db.get_value("Patch Log", patch_log.name, "patch"), OLD_LINES[old])
		self.assertEqual(frappe.db.count("Patch Log", {"patch": OLD_LINES[old]}), 1)
