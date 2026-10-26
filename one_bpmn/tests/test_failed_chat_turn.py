# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A failed agent turn in a looping chat map never replays the previous turn's answer."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.one_bpmn.patches.v1_0 import chat_agents_name_the_failure_reason as reason_fix
from one_bpmn.one_bpmn.patches.v1_0 import chat_agents_post_failed_turn_error as fix

BPMN_ID = "run_prosally_agent"
TURN_ONE_REPLY = "Here is the leave approval diagram you asked for."

# ProsAlly Save Response as it runs on the BA site, before the patch.
PROSALLY_SAVE_RESPONSE = """import json
conversation_id = task_data.get("conversation_id", context_docname)
from one_bpmn.agents.turn_state import get_turn, clear_turn
_turn = get_turn(conversation_id)
_out = _turn.get("output") if isinstance(_turn, dict) else None

_agent_text = task_data.get("ai_result")
if isinstance(_agent_text, dict):
    _agent_text = _agent_text.get("response") or _agent_text.get("text") or ""
if not isinstance(_agent_text, str):
    _agent_text = ""
_agent_text = _agent_text.strip()

if isinstance(_out, dict) and _out:
    response_text = _out.get("response") or _agent_text or "Could you tell me a bit more about the process you want to model?"
    intent = _out.get("intent")
    agent_result = _out
else:
    response_text = (task_data.get("response_text") or _agent_text
                     or "Could you tell me a bit more about the process you want to model?")
    intent = task_data.get("intent")
    agent_result = task_data.get("agent_result")
msg = frappe.new_doc("Chat Message")
msg.conversation = conversation_id
msg.sender = "Administrator"
msg.receiver = "User"
msg.text = response_text
msg.message_type = "Bot"
_meta = {"intent": intent}
if isinstance(agent_result, dict) and agent_result:
    _meta["agent_result"] = agent_result
msg.metadata = json.dumps(_meta, default=str)
msg.insert()
result["bot_message_name"] = msg.name
result["response_saved"] = True
result["turn_complete"] = True
clear_turn(conversation_id)
"""


class TurnFixture(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		# Turn one answered; its reply is still in task data when turn two starts.
		self.task = frappe._dict(
			{
				"data": {"ai_result": TURN_ONE_REPLY, f"{BPMN_ID}_output": TURN_ONE_REPLY},
				"task_spec": frappe._dict({"name": BPMN_ID, "description": "Run ProsAlly Agent"}),
			}
		)
		self.task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "draw it",
			"aiOutputVariable": "ai_result",
		}

	def _dispatch(self, result: ExecutorResult, refusal: str | None = None):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		with (
			patch("one_bpmn.agents.model_health.refuse_new_run", return_value=refusal),
			patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", return_value=result),
		):
			dispatchers.dispatch_ai_agent(self.instance, self.task, self.task_cfg, BPMN_ID)


class TestAFailedTurnBlanksTheOutput(TurnFixture):
	def test_an_executor_error_clears_the_previous_answer(self):
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.FAILED_MODEL_CALL,
				error_message="Credit balance is too low",
				token_usage=TokenUsage(),
				trace=[],
			)
		)
		self.assertIsNone(self.task.data["ai_result"])
		self.assertIsNone(self.task.data[f"{BPMN_ID}_output"])
		self.assertEqual(self.task.data[f"{BPMN_ID}_error_message"], "Credit balance is too low")

	def test_a_refused_model_clears_the_previous_answer(self):
		self._dispatch(
			ExecutorResult(error_code=ErrorCode.SUCCESS, output="unused"), refusal="Credit balance is too low"
		)
		self.assertIsNone(self.task.data["ai_result"])
		self.assertEqual(self.task.data[f"{BPMN_ID}_error_code"], ErrorCode.PROVIDER_DISABLED.value)

	def test_a_later_success_drops_the_earlier_error_code(self):
		self.task.data[f"{BPMN_ID}_error_code"] = ErrorCode.FAILED_MODEL_CALL.value
		self.task.data[f"{BPMN_ID}_error_message"] = "Credit balance is too low"
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.SUCCESS,
				output="A new diagram.",
				token_usage=TokenUsage(),
				trace=[],
			)
		)
		self.assertEqual(self.task.data["ai_result"], "A new diagram.")
		self.assertNotIn(f"{BPMN_ID}_error_code", self.task.data)


class TestSaveResponsePostsTheError(TurnFixture):
	def _save_response(self, script: str, task_data: dict) -> dict:
		conversation = frappe.get_doc(
			{
				"doctype": "Chat Conversation",
				"agent_mode": "AI Assistant",
				"title": f"Failed turn test {frappe.generate_hash(length=6)}",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		result = {}
		exec(
			script,
			{
				"frappe": frappe,
				"task_data": dict(task_data, conversation_id=conversation.name),
				"result": result,
				"context_docname": conversation.name,
			},
		)
		return frappe.get_doc("Chat Message", result["bot_message_name"])

	def test_the_second_turn_posts_the_error_not_turn_ones_reply(self):
		self._dispatch(
			ExecutorResult(error_code=ErrorCode.SUCCESS, output="unused"), refusal="Credit balance is too low"
		)
		script = fix.apply_edit(
			PROSALLY_SAVE_RESPONSE, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR
		)
		message = self._save_response(script, self.task.data)
		self.assertEqual(
			message.text,
			"The AI provider rejected the request: Credit balance is too low. Please try again in a few minutes.",
		)
		self.assertEqual(json.loads(message.metadata)["intent"], "ERROR")

	def test_a_successful_turn_still_posts_its_reply(self):
		script = fix.apply_edit(
			PROSALLY_SAVE_RESPONSE, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR
		)
		message = self._save_response(script, {"ai_result": TURN_ONE_REPLY})
		self.assertEqual(message.text, TURN_ONE_REPLY)

	def _reason_script(self) -> str:
		script = fix.apply_edit(
			PROSALLY_SAVE_RESPONSE, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR
		)
		return fix.apply_edit(script, reason_fix.OLD_LINE, reason_fix.NEW_LINES)

	def test_a_budget_stop_is_not_blamed_on_the_provider(self):
		message = self._save_response(
			self._reason_script(),
			{
				f"{BPMN_ID}_error_code": ErrorCode.BUDGET_EXCEEDED.value,
				f"{BPMN_ID}_error_message": "The run passed its token budget of 100 with 3,021 tokens.",
			},
		)
		self.assertEqual(
			message.text,
			"The agent stopped because this request went over its budget. Try a smaller request.",
		)
		self.assertEqual(json.loads(message.metadata)["intent"], "ERROR")

	def test_a_provider_error_keeps_the_provider_reply(self):
		self._dispatch(
			ExecutorResult(error_code=ErrorCode.SUCCESS, output="unused"), refusal="Credit balance is too low"
		)
		message = self._save_response(self._reason_script(), self.task.data)
		self.assertEqual(
			message.text,
			"The AI provider rejected the request: Credit balance is too low. Please try again in a few minutes.",
		)


class TestThePatchEdits(FrappeTestCase):
	def test_each_edit_applies_once(self):
		edited = fix.apply_edit(
			PROSALLY_SAVE_RESPONSE, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR
		)
		self.assertEqual(
			fix.apply_edit(edited, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR), edited
		)
		self.assertEqual(edited.count("_failed = task_data.get"), 1)

	def test_update_conversation_clears_ai_result(self):
		script = 'result["user_text"] = ""\nresult["intent"] = ""\n'
		edited = fix.apply_edit(script, fix.UPDATE_ANCHOR, f"{fix.UPDATE_ANCHOR}\n{fix.CLEAR_LINE}")
		result = {}
		exec(edited, {"result": result})
		self.assertIn("ai_result", result)
		self.assertIsNone(result["ai_result"])

	def test_a_script_without_a_single_anchor_is_not_edited(self):
		self.assertIsNone(fix.apply_edit("print(1)\n", fix.SAVE_ANCHOR, "x"))

	def test_the_reason_edit_applies_once(self):
		script = fix.apply_edit(
			PROSALLY_SAVE_RESPONSE, fix.SAVE_ANCHOR, fix.error_block(BPMN_ID) + fix.SAVE_ANCHOR
		)
		edited = fix.apply_edit(script, reason_fix.OLD_LINE, reason_fix.NEW_LINES)
		self.assertNotIn("The AI provider rejected", edited)
		self.assertEqual(fix.apply_edit(edited, reason_fix.OLD_LINE, reason_fix.NEW_LINES), edited)
