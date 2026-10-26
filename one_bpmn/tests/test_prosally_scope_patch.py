# Copyright (c) 2026, one-fm and contributors
"""A request about a sub-process on the diagram is classified as a modify, never a fresh draw."""

import ast
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import clear_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_scope_modify_to_subprocess as scope_patch
from one_bpmn.tests.test_prosally_subprocess_scope import DIAGRAM

CONVERSATION = "_test_prosally_scope_patch"
DRAW_REPLY = {"intent": "GENERATE_NEW", "reason": "r", "summary": {"intro": "i", "steps": [], "settings": []}, "question": "Shall I go ahead?"}


class FakeAdapter:
	def __init__(self, reply):
		self.reply = reply

	async def complete(self, system, user):
		return SimpleNamespace(text=json.dumps(self.reply))


class TestWithEdits(FrappeTestCase):
	def test_every_anchor_is_replaced_once(self):
		edited = scope_patch.with_edits("a b c", (("a", "A"), ("c", "C")))
		self.assertEqual(edited, "A b C")

	def test_an_anchor_that_is_missing_or_repeated_leaves_the_text_alone(self):
		self.assertIsNone(scope_patch.with_edits("a b", (("a", "A"), ("z", "Z"))))
		self.assertIsNone(scope_patch.with_edits("a a", (("a", "A"),)))


class TestScopedClassification(FrappeTestCase):
	def setUp(self):
		scope_patch.execute()
		self.script = frappe.db.get_value("Server Script", {"api_method": "prosally_tool_classify_intent"}, "script")
		if not self.script:
			self.skipTest("the ProsAlly Classify Intent script is not on this site")
		ast.parse(self.script)

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _classify(self, user_text, xml):
		set_turn(
			CONVERSATION,
			{"user_text": user_text, "process_name": "Doctype Sync", "current_xml": xml, "chat_history": []},
		)
		result = {}
		with patch(
			"one_bpmn.agents.prosally_helpers.get_llm_adapter_from_settings", return_value=FakeAdapter(DRAW_REPLY)
		):
			exec(self.script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result

	def test_a_request_naming_a_sub_process_is_a_modify(self):
		result = self._classify("Model the test subprocess as follows: Step 1 ...", DIAGRAM)
		self.assertEqual(result["intent"], "MODIFY_EXISTING")

	def test_a_request_naming_no_sub_process_keeps_the_classifier_answer(self):
		result = self._classify("Draw a leave request process", DIAGRAM)
		self.assertEqual(result["intent"], "GENERATE_NEW")

	def test_a_diagram_without_that_sub_process_keeps_the_classifier_answer(self):
		result = self._classify("Model the test subprocess as follows: Step 1 ...", "")
		self.assertEqual(result["intent"], "GENERATE_NEW")
