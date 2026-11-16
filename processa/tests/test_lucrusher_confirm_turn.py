# Copyright (c) 2026, one-fm and contributors
"""A confirmed LuCrusher stage stays confirmed on later turns, and a turn that never reached finalize says so."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_conversations.session_state import get_state, record
from processa.processa_engine.agent_runtime.turn_state import clear_turn, set_turn

DASH = chr(0x2013)
SAVE_RESPONSE = f"LuCrusher {DASH} Save Response"
BUILD_CONTEXT = f"LuCrusher {DASH} Build Context"
TASKS = {
	"processes": [{"process_name": "Manage 7-Day Absence Case", "tasks": [{"task": "a"}, {"task": "b"}]}]
}


class TestLuCrusherConfirmTurn(FrappeTestCase):
	def setUp(self):
		for name in (SAVE_RESPONSE, BUILD_CONTEXT):
			if not frappe.db.exists("Server Script", name):
				self.skipTest("LuCrusher is not on this site")
		self.save_script = frappe.db.get_value("Server Script", SAVE_RESPONSE, "script")
		self.build_script = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
		if "_CONFIRM_INTENTS" not in self.save_script:
			self.skipTest("the site's LuCrusher scripts predate the confirmed-stage memory")
		patcher = patch("processa.processa_engine.triggers.on_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.conversation = (
			frappe.get_doc({"doctype": "Chat Conversation", "title": "confirm probe"}).insert().name
		)
		self.addCleanup(clear_turn, self.conversation)

	def test_a_confirmed_task_list_stays_confirmed_after_a_later_question(self):
		self._save_response(
			{
				"context_state": {"migration_tasks": TASKS},
				"output": {"intent": "MIGRATION_TASKS_CONFIRMED", "response": "Confirmed."},
			}
		)
		self._save_response(
			{
				"context_state": get_state(self.conversation),
				"output": {"intent": "CLARIFY", "response": "Which one?"},
			}
		)

		state = get_state(self.conversation)
		self.assertEqual(state["intent"], "CLARIFY")
		self.assertEqual(state["confirmed"], ["MIGRATION_TASKS_CONFIRMED"])
		self.assertIn(
			"Migration tasks : 2 tasks across 1 process(es) [CONFIRMED by user]", self._state_block()
		)

	def test_a_turn_without_finalize_names_the_step_and_keeps_the_tasks(self):
		record(self.conversation, {"intent": "MIGRATION_TASKS_DRAFT", "migration_tasks": TASKS})

		text = self._save_response({"context_state": get_state(self.conversation)})

		self.assertIn("the finalize step never ran", text)
		self.assertIn("Your 2 migration tasks are still held", text)
		self.assertEqual(get_state(self.conversation)["migration_tasks"], TASKS)

	def test_a_turn_that_answered_in_prose_keeps_its_own_words(self):
		text = self._save_response({"context_state": {}}, ai_result="Here is what I found.")

		self.assertEqual(text, "Here is what I found.")

	def _save_response(self, turn: dict, ai_result="") -> str:
		set_turn(self.conversation, turn)
		scope = {
			"frappe": frappe,
			"context_docname": self.conversation,
			"task_data": {"conversation_id": self.conversation, "ai_result": ai_result},
			"result": {},
		}
		exec(self.save_script, scope)
		return frappe.db.get_value("Chat Message", scope["result"]["bot_message_name"], "text")

	def _state_block(self) -> str:
		scope = {
			"frappe": frappe,
			"context_docname": self.conversation,
			"task_data": {"conversation_id": self.conversation, "user_text": "hi"},
			"result": {},
			"agent_configuration": None,
			"instance": None,
		}
		with (
			patch("processa.ai_agent_skills.skill_tools.activate_skill", return_value="ok"),
			patch("processa.ai_agent_skills.skill_tools.deactivate_skill", return_value="ok"),
		):
			exec(self.build_script, scope)
		return scope["result"]["state_block"]
