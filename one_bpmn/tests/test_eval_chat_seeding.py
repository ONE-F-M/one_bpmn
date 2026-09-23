# Copyright (c) 2026, one-fm and contributors
"""A chat eval case can start from earlier turns, and never leaves its conversation open."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents import eval_runner
from one_bpmn.agents.memory import session_state
from one_bpmn.utils.chat_persistence import create_conversation

CFG = frappe._dict(agent_id="zz_eval_chat_agent", name="ZZ Eval Chat Agent")
CASE_NAME = "zz-eval-chat-seeding-case"


class TestChatEvalSeeding(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.conversations = []
		self.seen = {}

	def tearDown(self):
		for conversation in self.conversations:
			frappe.db.delete("Chat Message", {"conversation": conversation})
			if frappe.db.exists(session_state.STATE_DOCTYPE, conversation):
				session_state.clear_state(conversation)
				frappe.delete_doc(session_state.STATE_DOCTYPE, conversation, ignore_permissions=True, force=True)
			frappe.db.delete("Chat Conversation", {"name": conversation})
		frappe.db.delete("AI Agent Run", {"eval_case": CASE_NAME})
		frappe.db.commit()

	def _new_conversation(self, agent_id, title=None, user=None):
		conversation = create_conversation("ZZ Eval", title, user)
		self.conversations.append(conversation)
		return conversation

	def _record_turn(self, agent_id, message, conversation=None, context=None):
		self.seen = {
			"message": message,
			"conversation": conversation,
			"context": context,
			"history": frappe.get_all(
				"Chat Message",
				filters={"conversation": conversation},
				fields=["message_type", "text", "metadata"],
				order_by="creation asc",
			),
			"state": session_state.get_state(conversation),
		}
		# Tagged for both the agent_configuration and the eval_case run lookup.
		frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"agent_configuration": CFG.name,
				"eval_case": CASE_NAME,
				"origin": "eval",
				"bpmn_id": "zz_chat_turn",
				"status": "Success",
				"started_at": now_datetime(),
				"total_tokens": 7,
			}
		).insert(ignore_permissions=True, ignore_links=True)
		return {"response": "the reply"}

	def _run(self, input_context, invoke=None):
		case = frappe._dict(name=CASE_NAME, title="Seeded case", input_user_prompt="yes, the topology looks good",
			input_context=json.dumps(input_context))
		with (
			patch("one_bpmn.utils.chat_persistence.create_agent_conversation", side_effect=self._new_conversation),
			patch("one_bpmn.utils.chat_persistence.close_conversation") as close,
			patch("one_bpmn.api.agent_invocation.invoke_agent", side_effect=invoke or self._record_turn),
		):
			try:
				output, _usage = eval_runner._run_chat_agent_eval(CFG, case)
			except Exception as error:
				return error, close
			return output, close

	def test_earlier_turns_and_state_are_in_the_conversation_before_the_message(self):
		state = {"intent": "TOPOLOGY_PROPOSAL", "topology": {"total_processes": 2}}
		output, close = self._run(
			{
				"conversation_messages": [
					{"message_type": "User", "text": "analyse the topology"},
					{"message_type": "Bot", "text": "Here is the proposed topology."},
					{"message_type": "Tool", "text": "__lucrusher_state__", "metadata": state},
				],
				"session_state": {"lucid_doc:abc": {"title": "Visa"}},
				"page": "migration",
			}
		)
		self.assertEqual(output, "the reply")
		history = self.seen["history"]
		self.assertEqual([m.message_type for m in history], ["User", "Bot", "Tool"])
		self.assertEqual(history[1].text, "Here is the proposed topology.")
		self.assertEqual(json.loads(history[2].metadata), state)
		self.assertEqual(self.seen["state"]["lucid_doc:abc"], {"title": "Visa"})
		self.assertEqual(self.seen["context"], {"page": "migration"})
		self.assertEqual(self.seen["conversation"], self.conversations[0])
		close.assert_called_once_with(self.conversations[0])

	def test_a_case_with_no_seed_still_gets_its_own_conversation(self):
		output, close = self._run({})
		self.assertEqual(output, "the reply")
		self.assertEqual(self.seen["history"], [])
		self.assertEqual(self.seen["conversation"], self.conversations[0])
		close.assert_called_once_with(self.conversations[0])

	def test_the_conversation_is_closed_when_the_turn_fails(self):
		def fail(*args, **kwargs):
			raise frappe.ValidationError("agent failed")

		error, close = self._run({}, invoke=fail)
		self.assertIsInstance(error, frappe.ValidationError)
		close.assert_called_once_with(self.conversations[0])

	def test_an_unknown_message_type_is_refused(self):
		error, close = self._run({"conversation_messages": [{"message_type": "Robot", "text": "hi"}]})
		self.assertIsInstance(error, ValueError)
		self.assertIn("Robot", str(error))
		close.assert_called_once_with(self.conversations[0])
