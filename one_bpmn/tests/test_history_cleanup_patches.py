# Copyright (c) 2026, one-fm and contributors
"""The two data moves that come with the platform history step.

Shadow conversations the store wrote for nobody are deleted, and LuCrusher's
hidden state messages become session state so a resumed migration keeps its
place.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE
from one_bpmn.agents.memory.session_state import get_state
from one_bpmn.one_bpmn.patches.v1_0 import drop_agent_memory_shadow_conversations as drop_shadows
from one_bpmn.one_bpmn.patches.v1_0 import move_lucrusher_state_to_session_state as move_state
from one_bpmn.tests.conversation_fixtures import drop_conversations
from one_bpmn.utils.chat_persistence import create_conversation, save_user_message


def _tool_message(conversation: str, metadata: dict, text: str = move_state.STATE_SENTINEL) -> str:
	msg = frappe.get_doc({
		"doctype": "Chat Message",
		"conversation": conversation,
		"sender": "Administrator",
		"receiver": "LuCrusher",
		"text": text,
		"message_type": "Tool",
		"metadata": json.dumps(metadata),
	})
	with patch("frappe.enqueue"), patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
		msg.insert()
	return msg.name


class TestHistoryCleanupPatches(FrappeTestCase):
	def setUp(self):
		self.made = []

	def tearDown(self):
		drop_conversations(self.made)

	def _conversation(self, mode="Cleanup test"):
		with patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
			name = create_conversation(agent_mode=mode, title=f"Cleanup {frappe.generate_hash(length=8)}", user="Administrator")
		self.made.append(name)
		return name

	def test_shadow_conversations_go_and_real_ones_stay(self):
		shadow = self._conversation(mode=AGENT_MEMORY_MODE)
		real = self._conversation(mode="Docu")
		with patch("frappe.enqueue"), patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
			save_user_message(shadow, "copy of a prompt")
			save_user_message(real, "a real question")

		drop_shadows.execute()

		self.assertFalse(frappe.db.exists("Chat Conversation", shadow))
		self.assertEqual(frappe.db.count("Chat Message", {"conversation": shadow}), 0)
		self.assertTrue(frappe.db.exists("Chat Conversation", real))
		self.assertEqual(frappe.db.count("Chat Message", {"conversation": real}), 1)

	def test_the_latest_lucrusher_snapshot_becomes_session_state(self):
		name = self._conversation()
		_tool_message(name, {"intent": "PROCESS_CONFIRMED", "confirmed_process": {"name": "Old"}})
		_tool_message(name, {"intent": "TOPOLOGY_DRAFT", "confirmed_process": {"name": "Onboarding"},
		                     "topology": {"total_processes": 2}})

		move_state.execute()

		state = get_state(name)
		self.assertEqual(state["intent"], "TOPOLOGY_DRAFT")
		self.assertEqual(state["confirmed_process"], {"name": "Onboarding"})
		self.assertEqual(state["topology"], {"total_processes": 2})
		self.assertEqual(frappe.db.count("Chat Message", {"conversation": name, "message_type": "Tool"}), 0)

	def test_a_sentinel_wrapped_snapshot_is_unwrapped(self):
		name = self._conversation()
		_tool_message(name, {move_state.STATE_SENTINEL: {"intent": "CLARIFY"}})

		move_state.execute()

		self.assertEqual(get_state(name)["intent"], "CLARIFY")

	def test_unreadable_metadata_is_skipped_not_fatal(self):
		name = self._conversation()
		msg = _tool_message(name, {})
		frappe.db.set_value("Chat Message", msg, "metadata", "{not json", update_modified=False)

		move_state.execute()

		self.assertEqual(get_state(name), {})
		self.assertFalse(frappe.db.exists("Chat Message", msg))
