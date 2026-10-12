# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu's Tool Write Schema calls the writer with the Docu - Schema Writer record's prompt."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_writer_reads_its_own_prompt as fix

WRITER_PROMPT = "You are Docu, an expert assistant that designs Frappe DocTypes."

# The lines of Tool Write Schema around the writer call, as they run on the BA site before the patch.
WRITE_SCHEMA = """from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
_cfg = get_agent_config("docu_agent") or {}
_subs = _cfg.get("sub_prompts") or {}
if not turn.get("content_free"):
    _system = (_subs.get("schema_writer") or {}).get("prompt") or ""
    result["system"] = _system
"""

CONFIGS = {
	"docu_agent": {"sub_prompts": {"intent_classifier": {"prompt": "classify"}}},
	"docu_schema_writer": {"system_prompt": WRITER_PROMPT},
}


class TestDocuWriterPrompt(FrappeTestCase):
	def _run(self, script: str) -> str:
		result = {}
		with patch(
			"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
			side_effect=CONFIGS.get,
		):
			exec(script, {"frappe": frappe, "turn": {}, "result": result})
		return result["system"]

	def _write_schema_script(self) -> str:
		name = frappe.db.get_value("Server Script", {"api_method": fix.API_METHOD}, "name")
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": "Docu Writer Prompt Test",
					"script_type": "API",
					"api_method": fix.API_METHOD,
					"script": WRITE_SCHEMA,
				}
			)
			doc.insert(ignore_permissions=True)
			name = doc.name
		frappe.db.set_value("Server Script", name, "script", WRITE_SCHEMA)
		return name

	def test_the_writer_gets_its_record_prompt_and_the_design_rules(self):
		name = self._write_schema_script()
		fix.execute()
		system = self._run(frappe.db.get_value("Server Script", name, "script"))
		self.assertTrue(system.startswith(WRITER_PROMPT))
		self.assertIn("# The form design rules", system)

	def test_the_patch_applies_once(self):
		name = self._write_schema_script()
		fix.execute()
		once = frappe.db.get_value("Server Script", name, "script")
		fix.execute()
		self.assertEqual(frappe.db.get_value("Server Script", name, "script"), once)
		self.assertEqual(once.count('get_agent_config("docu_schema_writer")'), 1)

	def test_a_script_without_the_anchor_is_left_alone(self):
		name = self._write_schema_script()
		frappe.db.set_value("Server Script", name, "script", "result['system'] = 'x'\n")
		fix.execute()
		self.assertEqual(frappe.db.get_value("Server Script", name, "script"), "result['system'] = 'x'\n")
