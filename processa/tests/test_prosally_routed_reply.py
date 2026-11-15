# Copyright (c) 2026, one-fm and contributors
"""A ProsAlly turn with no reply is a NO_STAGE_REPLY failure, a skipped routed tool runs in finalize, and clarify names the missing piece."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_observability.terminal_tool import terminal_tool_failure
from processa.ai_agent_registry.definitions.prosally import tools_route
from processa.patches.v1_0 import seed_prosally_confirmed_brief_cases as seed
from processa.processa_engine.agent_runtime.executor import ErrorCode
from processa.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn

CONV = "zz-prosally-route"
FINALIZE = f"ProsAlly {chr(0x2013)} Tool Finalize"
CLARIFY = f"ProsAlly {chr(0x2013)} Tool Clarify"
GENERIC = "Could you tell me more about the process you'd like to model?"
FAILED_FINALIZE = '{"error": "NO_STAGE_REPLY: no stage wrote a reply", "error_code": "NO_STAGE_REPLY"}'


class TestTerminalToolError(FrappeTestCase):
	def test_the_error_code_is_in_the_enum(self):
		self.assertEqual(ErrorCode.NO_STAGE_REPLY.value, "NO_STAGE_REPLY")

	def test_a_last_tool_that_names_a_code_fails_the_run(self):
		trace = [
			{"tool_calls": [{"name": "classify_intent", "result": '{"next": "clarify"}'}]},
			{"tool_calls": [{"name": "finalize", "result": FAILED_FINALIZE}]},
		]

		self.assertEqual(
			terminal_tool_failure(trace),
			{
				"status": "Error",
				"error_code": "NO_STAGE_REPLY",
				"error_message": "NO_STAGE_REPLY: no stage wrote a reply",
			},
		)

	def test_an_error_without_a_code_or_a_clean_finalize_leaves_the_run_alone(self):
		clean = [{"tool_calls": [{"name": "finalize", "result": '{"finalized": true}'}]}]
		uncoded = [{"tool_calls": [{"name": "x", "result": '{"error": "boom"}'}]}]

		self.assertEqual(terminal_tool_failure(clean), {})
		self.assertEqual(terminal_tool_failure(uncoded), {})
		self.assertEqual(terminal_tool_failure([]), {})


class TestRouteHelpers(FrappeTestCase):
	def setUp(self):
		self.addCleanup(clear_turn, CONV)

	def test_no_stage_reply_names_the_failure_and_marks_the_turn(self):
		set_turn(CONV, {"user_text": "Yes, proceed"})

		envelope = tools_route.no_stage_reply(CONV)

		turn = get_turn(CONV)
		self.assertEqual(envelope["error_code"], "NO_STAGE_REPLY")
		self.assertEqual(turn["tool_error"]["error_code"], "NO_STAGE_REPLY")
		self.assertIn("NO_STAGE_REPLY", turn["output"]["response"])
		self.assertNotIn(GENERIC, turn["output"]["response"])
		self.assertTrue(turn["done"])

	def test_the_missing_piece_question_follows_the_reason(self):
		self.assertIn("lane", tools_route.missing_piece_question("no lanes named"))
		self.assertIn("starts", tools_route.missing_piece_question("the trigger is unknown"))
		self.assertIn("finished", tools_route.missing_piece_question("end state missing"))
		self.assertIn("called", tools_route.missing_piece_question(""))

	def test_clarify_without_a_model_answer_asks_for_the_missing_piece(self):
		set_turn(CONV, {"user_text": "draw it", "intent_reason": "no lanes named", "chat_history": []})

		with patch.object(tools_route, "complete_sub_prompt", return_value="not json"):
			out = tools_route.clarify_output(CONV)

		self.assertIn("lane", out["response"])
		self.assertEqual(get_turn(CONV)["output"]["intent"], "CLARIFY")

	def test_clarify_keeps_the_model_question_and_options(self):
		set_turn(CONV, {"user_text": "draw it", "intent_reason": "", "chat_history": []})
		reply = json.dumps({"question": "Who starts it?", "options": ["HR", "Employee"]})

		with patch.object(tools_route, "complete_sub_prompt", return_value=reply):
			out = tools_route.clarify_output(CONV)

		self.assertEqual((out["response"], out["options"]), ("Who starts it?", ["HR", "Employee"]))


class TestFinalizeRunsTheRoutedTool(FrappeTestCase):
	"""Runs the site's Finalize script the way the map does."""

	def setUp(self):
		for name in (FINALIZE, CLARIFY):
			if not frappe.db.exists("Server Script", name):
				self.skipTest("ProsAlly is not on this site")
		self.script = frappe.db.get_value("Server Script", FINALIZE, "script")
		if "no_stage_reply" not in self.script:
			self.skipTest("the site's Finalize script predates the routed reply")
		self.addCleanup(clear_turn, CONV)

	def _finalize(self, turn: dict) -> dict:
		set_turn(CONV, turn)
		result = {}
		exec(self.script, {"frappe": frappe, "context_docname": CONV, "result": result, "instance": None})
		return result

	def test_the_generic_sentence_is_gone_from_both_scripts(self):
		for name in (FINALIZE, CLARIFY):
			self.assertNotIn(GENERIC, frappe.db.get_value("Server Script", name, "script"))

	def test_a_skipped_clarify_runs_in_finalize(self):
		reply = '{"question": "Which lanes?", "options": []}'
		with patch.object(tools_route, "complete_sub_prompt", return_value=reply):
			result = self._finalize(
				{"user_text": "x", "routed_tool": "clarify", "intent_reason": "no lanes", "chat_history": []}
			)

		self.assertEqual(result["ran"], "clarify")
		self.assertEqual(get_turn(CONV)["output"]["response"], "Which lanes?")

	def test_a_turn_with_no_reply_at_all_fails_with_the_code(self):
		result = self._finalize({"user_text": "Yes, proceed"})

		self.assertEqual(result["error_code"], "NO_STAGE_REPLY")
		self.assertIn("NO_STAGE_REPLY", get_turn(CONV)["output"]["response"])

	def test_a_turn_already_answered_is_left_alone(self):
		output = {"intent": "BPMN_GENERATED", "response": "Drawn.", "options": []}
		result = self._finalize({"routed_tool": "generate_process", "output": output, "done": True})

		self.assertEqual(result, {"finalized": True})
		self.assertEqual(get_turn(CONV)["output"], output)


class TestConfirmedBriefCases(FrappeTestCase):
	def test_five_cases_are_seeded_once_with_the_brief_and_the_card(self):
		if not frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name"):
			self.skipTest("the ProsAlly Baseline suite is not on this site")

		seed.execute()
		seed.execute()

		titles = [c["title"] for c in json.loads(seed.BRIEFS.read_text())]
		cases = frappe.get_all(
			"AI Eval Case", filters={"title": ["in", titles]}, fields=["name", "input_context"]
		)
		self.assertEqual(len(cases), 5)
		context = json.loads(cases[0].input_context)
		self.assertEqual([m["message_type"] for m in context["conversation_messages"]], ["User", "Bot"])
		self.assertEqual(context["conversation_messages"][1]["metadata"]["intent"], "CONFIRM")
		case = frappe.get_doc("AI Eval Case", cases[0].name)
		self.assertEqual(case.input_user_prompt, "Yes, proceed")
		self.assertEqual(
			[c.tool_name for c in case.expected_tool_calls], ["classify_intent", "generate_process"]
		)
