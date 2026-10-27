# Copyright (c) 2026, one-fm and contributors
"""Where a turn stands after the browser lost its stream.

The turn keeps running on the worker when the stream drops, so the panel asks
for its reply instead of reporting a failure. These tests cover the three
answers (done, running, lost) and the reads that must never leak: another
user's conversation, and a reply that belongs to a later message.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.agui import turn_status
from one_bpmn.tests.test_chat_history_restore import CHOICE, _remove
from one_bpmn.utils.chat_persistence import create_conversation, save_bot_message, save_user_message

MESSAGE_ID = "m-turn-status-1"
JOB_RUNNING = "one_bpmn.agents.turn_signal.ai_job_running"


def _ask(conversation: str, text: str, client_message_id: str) -> str:
	name = save_user_message(conversation, text)
	frappe.db.set_value("Chat Message", name, "client_message_id", client_message_id, update_modified=False)
	return name


def _instance_for(conversation: str):
	doc = frappe.new_doc("BPMN Process Instance")
	doc.context_doctype = "Chat Conversation"
	doc.context_docname = conversation
	doc.db_insert()
	return doc


class TestTurnStatus(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = create_conversation("prosally", "_Test turn status", frappe.session.user)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("BPMN Process Instance", {"context_docname": self.conversation})
		_remove(self.conversation)

	def test_a_saved_reply_comes_back_with_its_events(self):
		_ask(self.conversation, "draw me a process", MESSAGE_ID)
		reply = save_bot_message(self.conversation, "Apply this topology?", metadata=CHOICE)

		status = turn_status(self.conversation, MESSAGE_ID)

		self.assertEqual(status["state"], "done")
		self.assertEqual([r["message"] for r in status["replies"]], [reply])
		self.assertEqual(status["replies"][0]["text"], "Apply this topology?")
		self.assertEqual([e["name"] for e in status["replies"][0]["events"]], ["onefm.choice"])

	def test_a_turn_with_a_job_still_queued_is_running_even_if_a_reply_exists(self):
		_ask(self.conversation, "draw me a process", MESSAGE_ID)
		save_bot_message(self.conversation, "first bubble")
		_instance_for(self.conversation)

		with patch(JOB_RUNNING, return_value=True):
			self.assertEqual(turn_status(self.conversation, MESSAGE_ID), {"state": "running"})

	def test_no_reply_and_no_job_is_lost(self):
		_ask(self.conversation, "draw me a process", MESSAGE_ID)
		_instance_for(self.conversation)

		with patch(JOB_RUNNING, return_value=False):
			self.assertEqual(turn_status(self.conversation, MESSAGE_ID), {"state": "lost"})

	def test_an_id_that_was_never_sent_is_lost(self):
		_ask(self.conversation, "draw me a process", MESSAGE_ID)
		save_bot_message(self.conversation, "an answer")

		self.assertEqual(turn_status(self.conversation, "m-never-sent"), {"state": "lost"})

	def test_a_reply_to_a_later_message_is_not_this_turns_reply(self):
		_ask(self.conversation, "first question", MESSAGE_ID)
		_ask(self.conversation, "second question", "m-turn-status-2")
		save_bot_message(self.conversation, "answer to the second")

		self.assertEqual(turn_status(self.conversation, MESSAGE_ID), {"state": "lost"})

	def test_another_users_conversation_reads_as_lost(self):
		_ask(self.conversation, "draw me a process", MESSAGE_ID)
		save_bot_message(self.conversation, "private answer")

		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			turn_status(self.conversation, MESSAGE_ID)

		frappe.set_user("test@example.com")
		self.assertEqual(turn_status(self.conversation, MESSAGE_ID), {"state": "lost"})
