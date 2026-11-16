from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import docu_defaults_to_processa_engine as patch

OLD_LINE = f'module = (target_module or "{patch.OLD}")'
OLD_PROMPT = f'"module": "{patch.OLD}",   // always the module you are told to use (default {patch.OLD})'


def put(doctype: str, name: str, fieldname: str, value: str) -> None:
	"""Give the named record this value, inserting a bare record when the site has none."""
	frappe.db.delete(doctype, {"name": name})
	frappe.get_doc({"doctype": doctype, "name": name, fieldname: value}).db_insert()


class TestDocuDefaultsToProcessaEngine(FrappeTestCase):
	def test_scripts_prompt_and_map_default_to_processa_engine(self):
		for script_name in patch.SCRIPT_NAMES:
			put("Server Script", script_name, "script", OLD_LINE)
		put("AI Agent Configuration", patch.AGENT_NAME, "system_prompt", OLD_PROMPT)
		put("BPMN Process Model", patch.MODEL_NAME, "bpmn_xml", f"<x>{OLD_PROMPT}</x>")

		with mock_patch("processa.api.deploy.compile_process_model") as compile_map:
			patch.execute()

		for script_name in patch.SCRIPT_NAMES:
			self.assertEqual(
				frappe.db.get_value("Server Script", script_name, "script"),
				'module = (target_module or "Processa Engine")',
			)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", patch.AGENT_NAME, "system_prompt"),
			'"module": "Processa Engine",   // always the module you are told to use (default Processa Engine)',
		)
		self.assertNotIn(patch.OLD, frappe.db.get_value("BPMN Process Model", patch.MODEL_NAME, "bpmn_xml"))
		compile_map.assert_called_once_with(patch.MODEL_NAME)

	def test_a_second_run_leaves_the_map_alone(self):
		put("BPMN Process Model", patch.MODEL_NAME, "bpmn_xml", "<x>Processa Engine</x>")

		with mock_patch("processa.api.deploy.compile_process_model") as compile_map:
			patch.execute()

		compile_map.assert_not_called()
