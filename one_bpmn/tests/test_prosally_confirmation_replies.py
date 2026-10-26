# Copyright (c) 2026, one-fm and contributors
"""A typed yes confirms, a typed no goes to clarify, and an instruction not to ask skips the question."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_classifier_skip_confirmation as classifier_patch

CLASSIFY_API_METHOD = "prosally_tool_classify_intent"
CONVERSATION = "_test_prosally_confirmation"


class TestConfirmationReply(FrappeTestCase):
	def test_affirmations_and_the_approve_button(self):
		for text in ("yes", "Yes, proceed", "ok go ahead!", "Go ahead please", "<p>Sure</p>", "That's right"):
			self.assertEqual(helpers.confirmation_reply(text), "yes", text)

	def test_declines_and_the_adjust_button(self):
		for text in ("No, let me adjust", "no", "Wait", "change the second lane", "not yet", "Don't"):
			self.assertEqual(helpers.confirmation_reply(text), "no", text)

	def test_a_reply_that_adds_detail_is_neither(self):
		for text in ("yes but add an HR lane", "draw a leave process", "", "nothing"):
			self.assertEqual(helpers.confirmation_reply(text), "", text)


class TestAnswerToConfirmation(FrappeTestCase):
	def _answer(self, metadata, text):
		rows = [frappe._dict(metadata=json.dumps(metadata))] if metadata is not None else []
		with patch.object(frappe, "get_all", return_value=rows):
			return helpers.answer_to_confirmation(CONVERSATION, text)

	def test_yes_to_a_confirmation_confirms_its_action(self):
		meta = {"intent": "CONFIRM", "agent_result": {"action_intent": "MODIFY_EXISTING"}}
		self.assertEqual(self._answer(meta, "yes"), {"confirmed_action": "MODIFY_EXISTING"})
		self.assertEqual(self._answer(meta, "no, wait"), {"declined_action": "MODIFY_EXISTING"})

	def test_yes_after_anything_but_a_confirmation_is_left_to_the_classifier(self):
		self.assertEqual(self._answer({"intent": "CLARIFY", "agent_result": {}}, "yes"), {})
		self.assertEqual(self._answer(None, "yes"), {})


class TestClassifyScript(FrappeTestCase):
	"""Runs the live Classify Intent Server Script; the script reaches a site with the ProsAlly map by export."""

	def setUp(self):
		self.script = frappe.db.get_value("Server Script", {"api_method": CLASSIFY_API_METHOD}, "script")
		if not self.script:
			self.skipTest("the ProsAlly Classify Intent script is not on this site")

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _classify(self, turn, model_reply=""):
		set_turn(CONVERSATION, {"user_text": "x", "process_name": "Leave", "current_xml": "", **turn})
		result = {}
		with patch.object(helpers, "complete_sub_prompt", return_value=model_reply) as model:
			exec(self.script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result, model

	def test_a_typed_yes_draws_without_a_model_call(self):
		result, model = self._classify({"confirmed_action": "GENERATE_NEW"})
		self.assertEqual(result["next"], "generate_process")
		model.assert_not_called()

	def test_a_typed_no_goes_to_clarify(self):
		result, model = self._classify({"declined_action": "GENERATE_NEW"})
		self.assertEqual(result["next"], "clarify")
		self.assertTrue(get_turn(CONVERSATION)["intent_reason"])
		model.assert_not_called()

	def test_skip_confirmation_draws_straight_away(self):
		reply = {"intent": "MODIFY_EXISTING", "reason": "r", "summary": "s", "question": "q?"}
		result, _ = self._classify({}, json.dumps({**reply, "skip_confirmation": True}))
		self.assertEqual(result["next"], "modify_process")
		self.assertTrue(get_turn(CONVERSATION)["confirmed"])
		result, _ = self._classify({}, json.dumps({**reply, "skip_confirmation": False}))
		self.assertEqual(result["next"], "finalize")
		self.assertEqual(get_turn(CONVERSATION)["output"]["intent"], "CONFIRM")


class TestClassifierPatch(FrappeTestCase):
	def test_the_rule_and_the_field_are_added_once(self):
		text = "Rules:\n" + classifier_patch.RULE_ANCHOR + "Respond:\n{" + classifier_patch.SHAPE_OLD
		row = frappe._dict(sub_agent_id="intent_classifier", prompt_text=text)
		doc = frappe._dict(sub_prompts=[row])
		doc.save = lambda **kwargs: None
		with (
			patch.object(frappe.db, "get_value", return_value="prosally"),
			patch.object(frappe, "get_doc", return_value=doc),
		):
			classifier_patch.execute()
			classifier_patch.execute()
		self.assertEqual(row.prompt_text.count(classifier_patch.RULE), 1)
		self.assertIn(classifier_patch.SHAPE_NEW, row.prompt_text)
		self.assertNotIn(classifier_patch.SHAPE_OLD, row.prompt_text)
