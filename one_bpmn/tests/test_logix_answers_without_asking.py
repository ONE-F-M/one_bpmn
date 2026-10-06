# Copyright (c) 2026, one-fm and contributors
"""A Logix question about the linked script is answered without asking one back."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_answers_without_asking as p
from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite as seed

QUESTIONS = (
	"QUESTIONS:\n"
	"When the person asks about the linked script (what it does, why it failed) and asks for no change, "
	"answer in two or three plain sentences and write no code block. Do not rewrite the script."
)
SENTENCE = "Do not ask the person anything back."
OTHER_CASE = "A shell command in the request never reaches the script"


class TestLogixAnswersWithoutAsking(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._stub_agent(seed.AGENT_ID, "ZZ Logix Stub")
		self._stub_agent(p.WRITER_AGENT_ID, "ZZ Logix Writer Stub")
		self.writer = frappe.db.get_value("AI Agent Configuration", {"agent_id": p.WRITER_AGENT_ID})
		frappe.db.set_value("AI Agent Configuration", self.writer, "system_prompt", QUESTIONS)
		seed.execute()

	def _stub_agent(self, agent_id: str, agent_name: str):
		if frappe.db.exists("AI Agent Configuration", {"agent_id": agent_id}):
			return
		map_name = frappe.db.get_value("BPMN Process Model", {"title": "zz-logix-stub-map"})
		if not map_name:
			model = frappe.get_doc(
				{"doctype": "BPMN Process Model", "title": "zz-logix-stub-map", "process_id": "zz_logix_stub", "version": 1}
			)
			model.flags.skip_editability_check = True
			model.flags.skip_script_security_check = True
			model.insert(ignore_permissions=True)
			map_name = model.name
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": agent_name,
				"agent_id": agent_id,
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"process_model": map_name,
			}
		).insert(ignore_permissions=True)

	def _prompt(self) -> str:
		return frappe.db.get_value("AI Agent Configuration", self.writer, "system_prompt")

	def _case(self, title: str):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		return frappe.get_doc("AI Eval Case", {"suite": suite, "title": title})

	def test_the_questions_rule_tells_the_writer_not_to_ask(self):
		p.execute()

		self.assertTrue(self._prompt().startswith(QUESTIONS))
		self.assertIn(SENTENCE, self._prompt())

	def test_running_twice_adds_the_sentence_once(self):
		p.execute()
		p.execute()

		self.assertEqual(self._prompt().count(SENTENCE), 1)

	def test_a_prompt_without_the_anchor_is_left_as_it_is(self):
		frappe.db.set_value("AI Agent Configuration", self.writer, "system_prompt", "You write scripts.")
		p.execute()

		self.assertEqual(self._prompt(), "You write scripts.")

	def test_the_seeded_question_case_names_one_thing_everywhere(self):
		context = json.dumps(next(c["context"] for c in seed.CASES if c["title"] == p.QUESTION_CASE))

		self.assertNotIn("Reason", context)
		self.assertNotIn("Mandaotry", context)

	def test_the_patch_refreshes_only_the_question_case(self):
		frappe.db.set_value("AI Eval Case", self._case(p.QUESTION_CASE).name, "input_context", '{"element_name": "Reason"}')
		frappe.db.set_value("AI Eval Case", self._case(OTHER_CASE).name, "input_context", '{"marker": 1}')
		p.execute()

		expected = json.dumps(next(c["context"] for c in seed.CASES if c["title"] == p.QUESTION_CASE))
		self.assertEqual(self._case(p.QUESTION_CASE).input_context, expected)
		self.assertEqual(self._case(OTHER_CASE).input_context, '{"marker": 1}')
