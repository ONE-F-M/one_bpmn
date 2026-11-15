# Copyright (c) 2026, one-fm and contributors
"""A layout instruction is laid out again or refused in words, and the crossing note is said once per conversation."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_replies, tools_review
from processa.patches.v1_0 import seed_prosally_layout_regression_cases as seed

NODES = [{"id": "g1", "name": "Recruiter Action?"}, {"id": "g2", "name": "Requester Action?"}]
NOT_PLANAR = {"planar": False, "obstruction": ["g1", "g2"]}
TWO_THINGS = ("drag shapes on the canvas", "change the flow structure")


class TestCrossingNote(FrappeTestCase):
	def setUp(self):
		patcher = patch("processa.processa_engine.triggers.on_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.conversation = (
			frappe.get_doc({"doctype": "Chat Conversation", "title": "crossing probe"}).insert().name
		)

	def _bot_said(self, text):
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation,
				"message_type": "Bot",
				"text": text,
			}
		).insert()

	def test_a_planar_layout_gets_no_note(self):
		self.assertEqual(tools_replies.crossing_line_note(NODES, {"planar": True}, self.conversation), "")

	def test_the_first_crossing_is_explained_with_the_steps_on_it(self):
		note = tools_replies.crossing_line_note(NODES, NOT_PLANAR, self.conversation)

		self.assertIn("One crossing line is unavoidable", note)
		self.assertIn("Recruiter Action?, Requester Action?", note)

	def test_the_note_is_not_repeated_in_the_same_conversation(self):
		self._bot_said(
			"I've updated the process. One crossing line is unavoidable: the paths through X cannot all be laid flat."
		)

		self.assertEqual(tools_replies.crossing_line_note(NODES, NOT_PLANAR, self.conversation), "")

	def test_another_conversation_hears_it_again(self):
		self._bot_said("One crossing line is unavoidable: the paths through X cannot all be laid flat.")
		other = frappe.get_doc({"doctype": "Chat Conversation", "title": "other"}).insert().name

		self.assertIn(
			"One crossing line is unavoidable", tools_replies.crossing_line_note(NODES, NOT_PLANAR, other)
		)


class TestRelayoutReply(FrappeTestCase):
	def test_a_redrawn_diagram_says_what_the_person_can_do_about_layout(self):
		with patch.object(tools_review, "relayout", return_value=("<xml />", "")):
			out = tools_review.relayout_output("<old />")

		self.assertEqual(out["action_intent"], "RELAYOUT")
		self.assertIn("Layout is computed automatically", out["response"])
		for thing in TWO_THINGS:
			self.assertIn(thing, out["response"])

	def test_an_unchanged_layout_still_names_the_two_things(self):
		with patch.object(tools_review, "relayout", return_value=(None, "same")):
			out = tools_review.relayout_output("<xml />")

		self.assertEqual(out["intent"], "CLARIFY")
		self.assertIn("already the best", out["response"])
		for thing in TWO_THINGS:
			self.assertIn(thing, out["response"])


class TestRegressionCases(FrappeTestCase):
	def _suite(self):
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		suite = agent and frappe.db.get_value(
			"AI Eval Suite", {"agent_configuration": agent, "title": ["like", seed.SUITE_TITLE_LIKE]}, "name"
		)
		if not suite:
			self.skipTest("ProsAlly and its Regressions suite are not on this site")
		return suite

	def test_the_three_instructions_expect_relayout_and_no_drawing_tool(self):
		suite = self._suite()

		seed.execute()
		seed.execute()

		titles = [t for t, _p in seed.PROMPTS]
		cases = frappe.get_all(
			"AI Eval Case", filters={"suite": suite, "title": ["in", titles]}, fields=["name", "title"]
		)
		self.assertEqual(sorted(c.title for c in cases), sorted(titles))
		case = frappe.get_doc("AI Eval Case", cases[0].name)
		self.assertEqual([a.assertion_type for a in case.assertions], ["regex", "no_tool_call"])
		self.assertIn("RELAYOUT", case.assertions[0].value)
		self.assertIn("modify_process", case.assertions[1].value)
		self.assertEqual([c.tool_name for c in case.expected_tool_calls], ["classify_intent"])
		self.assertIn("current_xml", case.input_context)
