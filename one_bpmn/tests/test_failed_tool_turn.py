# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A stage tool that fails is reported to the chat user as a failure, not as a request for more detail."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import execute_shape
from one_bpmn.agents.turn_state import get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import chat_agents_post_failed_turn_error as turn_fix
from one_bpmn.one_bpmn.patches.v1_0 import chat_agents_report_failed_tool as fix
from one_bpmn.tests.test_failed_chat_turn import PROSALLY_SAVE_RESPONSE

TOOL_FAILED_REPLY = "I could not draw the diagram because a tool failed. The team has been notified."

# ProsAlly Tool Finalize as it runs on the BA site, before the patch.
PROSALLY_FINALIZE = """from one_bpmn.agents.turn_state import get_turn, update_turn

turn = get_turn(context_docname)
if turn.get("done"):
    result["finalized"] = True
else:
    output = {
        "intent": "CLARIFY",
        "action_intent": None,
        "response": "Could you tell me more about the process you'd like to model?",
        "options": [],
    }
    update_turn(context_docname, output=output, done=True)
    result["finalized"] = True
    result["fallback"] = True
"""


def _patched(script: str, anchor: str, replacement: str) -> str:
	edited = turn_fix.apply_edit(script, anchor, replacement)
	assert edited is not None, anchor
	return edited


PATCHED_FINALIZE = _patched(PROSALLY_FINALIZE, fix.FINALIZE_ANCHOR, fix.FINALIZE_BLOCK + fix.FINALIZE_ANCHOR)
PATCHED_SAVE_RESPONSE = _patched(
	_patched(
		PROSALLY_SAVE_RESPONSE,
		turn_fix.SAVE_ANCHOR,
		turn_fix.error_block("run_prosally_agent") + turn_fix.SAVE_ANCHOR,
	),
	fix.PROSALLY_META_ANCHOR,
	f"{fix.PROSALLY_META_ANCHOR}\n{fix.CARRY_TOOL_ERROR}",
)


class ChatTurnFixture(FrappeTestCase):
	def setUp(self):
		self.conversation = frappe.get_doc(
			{
				"doctype": "Chat Conversation",
				"agent_mode": "AI Assistant",
				"title": f"Failed tool test {frappe.generate_hash(length=6)}",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		set_turn(self.conversation.name, {})
		self.instance = frappe._dict(
			_service_task_extensions={},
			context_doctype="Chat Conversation",
			context_docname=self.conversation.name,
			initiated_by="Administrator",
		)
		self.script = self._server_script("Failed Tool Import Script", "from json import no_such_name\n")

	def _server_script(self, name: str, body: str) -> str:
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": name.lower().replace(" ", "_"),
					"script": body,
				}
			).insert(ignore_permissions=True)
		return name

	def _exec(self, script: str, **names) -> dict:
		result = {}
		exec(script, {"frappe": frappe, "result": result, "context_docname": self.conversation.name, **names})
		return result


class TestTheFailureIsRecorded(ChatTurnFixture):
	def test_an_import_error_in_a_stage_script_lands_in_the_turn_store(self):
		out = execute_shape(self.instance, "generate_process", {"serverScript": self.script}, {})
		self.assertIn("error", json.loads(out))
		tool_error = get_turn(self.conversation.name)["tool_error"]
		self.assertEqual(tool_error["tool"], "generate_process")
		self.assertEqual(tool_error["error_class"], "ImportError")
		self.assertIn("no_such_name", tool_error["error"])

	def test_a_failure_outside_a_chat_conversation_writes_no_turn(self):
		self.instance.context_doctype = "Work Item"
		with patch("one_bpmn.agents.turn_state.update_turn") as update_turn:
			execute_shape(self.instance, "generate_process", {"serverScript": self.script}, {})
		update_turn.assert_not_called()


class TestTheUserIsToldItFailed(ChatTurnFixture):
	def test_the_failed_turn_posts_the_tool_failure_reply(self):
		execute_shape(self.instance, "generate_process", {"serverScript": self.script}, {})
		self.assertTrue(self._exec(PATCHED_FINALIZE)["tool_error"])
		result = self._exec(PATCHED_SAVE_RESPONSE, task_data={"conversation_id": self.conversation.name})

		message = frappe.get_doc("Chat Message", result["bot_message_name"])
		self.assertEqual(message.text, TOOL_FAILED_REPLY)
		self.assertNotIn("ImportError", message.text)
		metadata = json.loads(message.metadata)
		self.assertEqual(metadata["intent"], "TOOL_ERROR")
		self.assertEqual(metadata["tool_error"]["error_class"], "ImportError")

	def test_a_turn_with_no_stage_answer_and_no_failure_still_asks_for_detail(self):
		self.assertTrue(self._exec(PATCHED_FINALIZE)["fallback"])
		self.assertEqual(get_turn(self.conversation.name)["output"]["intent"], "CLARIFY")

	def test_a_stage_that_answered_keeps_its_reply(self):
		set_turn(
			self.conversation.name, {"done": True, "output": {"intent": "GENERATE", "response": "Done."}}
		)
		self.assertNotIn("tool_error", self._exec(PATCHED_FINALIZE))
		self.assertEqual(get_turn(self.conversation.name)["output"]["response"], "Done.")


class TestThePatchEdits(FrappeTestCase):
	def test_lucrusher_save_response_carries_the_tool_error(self):
		script = _patched(
			f"import json\n{fix.LUCRUSHER_META_ANCHOR}\n", fix.LUCRUSHER_META_ANCHOR, fix.LUCRUSHER_META
		)
		msg = frappe._dict()
		exec(
			script,
			{
				"_turn": {"tool_error": {"tool": "fetch_document", "error_class": "ImportError"}},
				"intent": "CLARIFY",
				"agent_result": {},
				"msg": msg,
			},
		)
		self.assertEqual(json.loads(msg.metadata)["tool_error"]["tool"], "fetch_document")

	def test_each_edit_applies_once(self):
		self.assertEqual(
			turn_fix.apply_edit(
				PATCHED_FINALIZE, fix.FINALIZE_ANCHOR, fix.FINALIZE_BLOCK + fix.FINALIZE_ANCHOR
			),
			PATCHED_FINALIZE,
		)
		self.assertEqual(PATCHED_FINALIZE.count('"TOOL_ERROR"'), 1)
		self.assertEqual(PATCHED_SAVE_RESPONSE.count(fix.CARRY_TOOL_ERROR), 1)
