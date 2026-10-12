# Copyright (c) 2026, one-fm and contributors
"""The three JSON agents stop asking for JSON in prose, and the Error Log schema requires ticket_name."""

import html
import json
import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider import structured_output
from one_bpmn.one_bpmn.patches.v1_0 import json_agents_declare_their_schema as p

PATCH_COMPILE = "one_bpmn.api.compilation.compile_process_model"


class TestJsonAgentsDeclareTheirSchema(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		xml = frappe.db.get_value("BPMN Process Model", p.MODEL_NAME, "bpmn_xml") or ""
		(prompt_line, _), (schema_old, schema_new) = p.MAP_EDITS
		xml = xml.replace(schema_new, schema_old, 1)
		if prompt_line not in xml:
			xml = re.sub(
				r'(<bpmn:serviceTask id="ai_similarity_check"[^>]*?aiUserPrompt="[^"]*)"',
				lambda m: m.group(1) + prompt_line + '"',
				xml,
				count=1,
			)
		cls.original_xml = xml

	def setUp(self):
		self.configs = {}
		for agent_id, (old, _new) in p.PROMPT_EDITS.items():
			name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
			if not name:
				self.skipTest(f"{agent_id} is not on this site")
			frappe.db.set_value(
				"AI Agent Configuration",
				name,
				"system_prompt",
				f"You classify things.\n\n{old}\n\nKeep it short.",
			)
			self.configs[agent_id] = name
		if not self.original_xml or any(self.original_xml.count(old) != 1 for old, _new in p.MAP_EDITS):
			self.skipTest(f"{p.MODEL_NAME} on this site is not the diagram the patch targets")
		frappe.db.set_value("BPMN Process Model", p.MODEL_NAME, "bpmn_xml", self.original_xml)

	def _prompt(self, agent_id):
		return frappe.db.get_value("AI Agent Configuration", self.configs[agent_id], "system_prompt")

	def _similarity_tag(self):
		xml = frappe.db.get_value("BPMN Process Model", p.MODEL_NAME, "bpmn_xml")
		return re.search(r'<bpmn:serviceTask id="ai_similarity_check"[^>]*>', xml).group(0)

	def test_prompts_drop_the_json_instruction_and_keep_the_field_meanings(self):
		with patch(PATCH_COMPILE):
			p.execute()
		for agent_id in p.PROMPT_EDITS:
			prompt = self._prompt(agent_id)
			self.assertNotIn(p.JSON_INSTRUCTION, prompt)
			self.assertIn("Keep it short.", prompt)
		self.assertIn('choices in "options"', self._prompt("logix_clarifier"))
		self.assertIn("Never invent a ticket_name", self._prompt("error_log_ticket_agent"))

	def test_error_log_schema_requires_ticket_name_and_the_prompt_stops_asking_for_json(self):
		with patch(PATCH_COMPILE) as compile_model:
			p.execute()
		tag = self._similarity_tag()
		schema = json.loads(html.unescape(re.search(r'aiResponseSchema="([^"]*)"', tag).group(1)))
		self.assertEqual(schema["required"], ["decision", "ticket_name"])
		self.assertTrue(structured_output.all_fields_required(schema))
		structured_output.validate_schema_rules(schema)
		self.assertNotIn("Respond with the JSON object", tag)
		compile_model.assert_called_once_with(p.MODEL_NAME)

	def test_a_second_run_changes_nothing(self):
		with patch(PATCH_COMPILE):
			p.execute()
		prompts = {agent_id: self._prompt(agent_id) for agent_id in p.PROMPT_EDITS}
		xml = frappe.db.get_value("BPMN Process Model", p.MODEL_NAME, "bpmn_xml")
		with patch(PATCH_COMPILE) as compile_model:
			p.execute()
		self.assertEqual(prompts, {agent_id: self._prompt(agent_id) for agent_id in p.PROMPT_EDITS})
		self.assertEqual(xml, frappe.db.get_value("BPMN Process Model", p.MODEL_NAME, "bpmn_xml"))
		compile_model.assert_not_called()

	def test_a_reworded_json_instruction_is_logged_and_left_alone(self):
		reworded = "Respond with ONLY a JSON object, please."
		frappe.db.set_value(
			"AI Agent Configuration", self.configs["logix_clarifier"], "system_prompt", reworded
		)
		with patch(PATCH_COMPILE), patch.object(frappe, "log_error") as log_error:
			p.execute()
		self.assertEqual(self._prompt("logix_clarifier"), reworded)
		log_error.assert_called_once()
