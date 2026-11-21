# Copyright (c) 2026, one-fm and contributors
"""What Logix's agent tool contract and reviewer now say about tools is what the tool runner does."""

import importlib

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_skills.tools import shape_tools
from processa.patches.v1_0 import logix_instructions_match_the_tool_runner as p

TOOL = "Logix Runner Fact Tool"
STALE = "\n\n".join(old for old, _new in p.FIXES)


class TestLogixInstructionsMatchTheToolRunner(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_every_stale_passage_is_replaced(self):
		text = p.fixed(STALE)
		for old, _new in p.FIXES:
			self.assertNotIn(old, text)
		self.assertIn("one namespace", text)
		self.assertIn("`task_data`: the calling agent task's workflow variables", text)

	def test_an_agent_tool_reads_task_data_and_its_arguments(self):
		if frappe.db.exists("Server Script", TOOL):
			frappe.delete_doc("Server Script", TOOL, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": TOOL,
				"script_type": "API",
				"api_method": "logix_runner_fact_tool",
				"script": 'result["seen"] = [task_data.get("stage"), project_name]',
			}
		).insert()
		task = shape_tools._synthetic_task("t", {"project_name": "Alpha"}, {"stage": "review"})
		shape_tools._run_server_script(frappe._dict(context_doctype="", context_docname=""), TOOL, task, "t")
		self.assertEqual(task.data["seen"], ["review", "Alpha"])

	def test_the_import_paths_the_text_names_exist(self):
		for _old, new in p.FIXES[-2:]:
			importlib.import_module(new)
		self.assertTrue(hasattr(importlib.import_module(p.FIXES[-1][1]), "execute_shape"))

	def test_the_patch_fixes_the_stored_skill(self):
		if frappe.db.exists("AI Skill", "bpmn-agent-tool-contract"):
			frappe.db.set_value("AI Skill", "bpmn-agent-tool-contract", "body", STALE)
		else:
			frappe.get_doc(
				{
					"doctype": "AI Skill",
					"skill_name": "bpmn-agent-tool-contract",
					"status": "Active",
					"description": "Agent tool contract",
					"body": STALE,
				}
			).insert()
		p.execute()
		body = frappe.db.get_value("AI Skill", "bpmn-agent-tool-contract", "body")
		self.assertEqual(body, p.fixed(STALE))
