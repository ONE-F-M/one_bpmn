# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A chat turn answered by a stage tool keeps that reply as its output and final_output."""

from __future__ import annotations

import frappe

from one_bpmn.agents import turn_state
from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.tests.test_failed_chat_turn import BPMN_ID, TurnFixture

STAGE_REPLY = "I added the manager approval step after the request."


class TestTheTurnStoreReplyBecomesTheOutput(TurnFixture):
	def setUp(self):
		super().setUp()
		self.conversation = frappe.get_doc(
			{
				"doctype": "Chat Conversation",
				"agent_mode": "AI Assistant",
				"title": f"Final output test {frappe.generate_hash(length=6)}",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		self.instance.context_doctype = "Chat Conversation"
		self.instance.context_docname = self.conversation.name
		turn_state.set_turn(self.conversation.name, {"output": {"response": STAGE_REPLY}, "done": True})

	def tearDown(self):
		turn_state.clear_turn(self.conversation.name)
		super().tearDown()

	def _final_output(self) -> str | None:
		return frappe.db.get_value("AI Agent Run", {"instance": self.instance.name}, "final_output")

	def test_an_empty_successful_output_takes_the_stage_reply(self):
		self._dispatch(
			ExecutorResult(error_code=ErrorCode.SUCCESS, output="", token_usage=TokenUsage(), trace=[])
		)

		self.assertEqual(self.task.data["ai_result"], STAGE_REPLY)
		self.assertEqual(self._final_output(), STAGE_REPLY)

	def test_narration_is_replaced_by_the_stage_reply(self):
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.SUCCESS,
				output="I'll process your request step by step.",
				token_usage=TokenUsage(),
				trace=[],
			)
		)

		self.assertEqual(self.task.data["ai_result"], STAGE_REPLY)
		self.assertEqual(self._final_output(), STAGE_REPLY)

	def test_a_finalize_marker_is_replaced_by_the_stage_reply(self):
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.SUCCESS,
				output='{"finalized": true, "tool_error": true}',
				token_usage=TokenUsage(),
				trace=[],
			)
		)

		self.assertEqual(self._final_output(), STAGE_REPLY)

	def test_without_a_stage_reply_the_text_is_kept(self):
		turn_state.clear_turn(self.conversation.name)
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.SUCCESS, output="Plain answer.", token_usage=TokenUsage(), trace=[]
			)
		)

		self.assertEqual(self._final_output(), "Plain answer.")

	def test_a_failed_run_keeps_its_output_blank(self):
		self._dispatch(
			ExecutorResult(
				error_code=ErrorCode.FAILED_MODEL_CALL,
				error_message="Credit balance is too low",
				token_usage=TokenUsage(),
				trace=[],
			)
		)

		self.assertIsNone(self.task.data["ai_result"])
		self.assertFalse(self._final_output())

	def test_a_dict_output_is_left_alone(self):
		parsed = {"answer": "yes"}
		self._dispatch(
			ExecutorResult(error_code=ErrorCode.SUCCESS, output=parsed, token_usage=TokenUsage(), trace=[])
		)

		self.assertEqual(self.task.data["ai_result"], parsed)
