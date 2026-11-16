import json
import sys
from unittest.mock import patch

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

		frappe.cache.delete_value("app_hooks")
		self.addCleanup(frappe.cache.delete_value, "app_hooks")
		with patch.dict(sys.modules, {"one_bpmn": None}):
			rename_app()
			rename_app()

		self.assertEqual(json.loads(frappe.db.get_global("installed_apps")), installed)
		self.assertEqual(frappe.db.get_value("Module Def", module.name, "app_name"), "processa")
		self.assertEqual(frappe.db.get_value("Patch Log", patch_log.name, "patch"), OLD_LINES[old])
		self.assertEqual(frappe.db.count("Patch Log", {"patch": OLD_LINES[old]}), 1)

	def test_rename_app_drops_the_cached_app_list_and_module_map(self):
		cached = ["defaults::__global", "app_modules", "installed_app_modules"]
		for key in cached:
			frappe.cache.set_value(key, {"one_bpmn": ["one_bpmn"]})
			self.addCleanup(frappe.cache.delete_value, key)
		self.addCleanup(frappe.cache.delete_value, "app_hooks")

		with patch.dict(sys.modules, {"one_bpmn": None}):
			rename_app()

		for key in cached:
			self.assertIsNone(frappe.cache.get_value(key), key)


class TestRenameStoredPathsBeforeApprovalFields(FrappeTestCase):
	def test_script_is_renamed_on_a_site_without_the_approval_columns(self):
		from processa.patches.v1_0 import rename_stored_one_bpmn_paths as rename_patch

		script = frappe.get_doc({"doctype": "Server Script", "name": "Cutover Approval Probe", "script_type": "API",
			"api_method": "cutover_approval_probe", "script": "from one_bpmn.agents.turn_state import get_turn", "disabled": 1})
		script.db_insert()
		real_get_value = frappe.db.get_value

		def get_value(doctype, name, fieldname, *args, **kwargs):
			if doctype == "Server Script" and "processa_approved" in str(fieldname):
				raise frappe.db.OperationalError(1054, "Unknown column 'processa_approved'")
			return real_get_value(doctype, name, fieldname, *args, **kwargs)

		with patch.object(frappe.db, "has_column", return_value=False), patch.object(frappe.db, "get_value", side_effect=get_value):
			rename_patch._rename_script(script.name)

		self.assertEqual(frappe.db.get_value("Server Script", script.name, "script"), "from processa.agents.turn_state import get_turn")
