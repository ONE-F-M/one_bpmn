# Copyright (c) 2026, one-fm and contributors
"""The stored ProsAlly scripts and classifier prompt know how to keep None tasks and replace tasks with them."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_draws_none_tasks as patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_turns_a_step_into_a_subprocess import AGENT_ID


def _script(pattern):
	name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
	return frappe.db.get_value("Server Script", name, "script") if name else ""


class TestProsallyDrawsNoneTasks(FrappeTestCase):
	def setUp(self):
		self.config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not self.config:
			self.skipTest("ProsAlly is not on this site")
		patch.execute()

	def _classifier_prompt(self):
		return frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.config, "sub_agent_id": "intent_classifier"}, "prompt_text"
		)

	def test_modify_marks_the_process_kind_before_it_compiles(self):
		script = _script("ProsAlly%Tool Modify Process")
		self.assertLess(script.index("keep_process_kind(ir_dict, current_xml)"), script.index("_res = compile_ir(ir_dict)"))

	def test_classify_runs_the_confirmed_replace_all_with_none(self):
		script = _script("ProsAlly%Tool Classify Intent")
		self.assertIn('if confirmed == "TASKS_TO_NONE":', script)
		self.assertIn("none_tasks_output(", script)

	def test_the_classifier_knows_the_new_intent(self):
		prompt = self._classifier_prompt()
		self.assertIn("classify as TASKS_TO_NONE", prompt)
		self.assertIn("RELAYOUT|TASKS_TO_NONE|COMPARE", prompt)

	def test_running_twice_edits_each_script_and_prompt_once(self):
		patch.execute()
		self.assertEqual(_script("ProsAlly%Tool Modify Process").count("keep_process_kind(ir_dict, current_xml)"), 1)
		self.assertEqual(_script("ProsAlly%Tool Classify Intent").count('if confirmed == "TASKS_TO_NONE":'), 1)
		self.assertEqual(self._classifier_prompt().count("classify as TASKS_TO_NONE"), 1)

	def test_the_edited_scripts_are_valid_python(self):
		for pattern in ("ProsAlly%Tool Modify Process", "ProsAlly%Tool Classify Intent"):
			compile(_script(pattern), pattern, "exec")
