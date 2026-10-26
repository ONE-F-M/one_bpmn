# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_eval_suite
from one_bpmn.agents.memory import session_state
from one_bpmn.api.eval_api import (
	conversation_context_for_case,
	get_conversation_for_case,
	list_conversations_for_case,
)

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


def _conversation(mode: str, rows: list, is_eval: int = 0) -> tuple[str, list]:
	"""A chat with ``rows`` of (message_type, text, metadata), one second apart, oldest first."""
	chat = frappe.get_doc({"doctype": "Chat Conversation", "title": f"zz-{frappe.generate_hash(length=6)}", "agent_mode": mode})
	chat.insert(ignore_permissions=True)
	if is_eval:
		frappe.db.set_value("Chat Conversation", chat.name, "is_eval", 1, update_modified=False)
	start = add_to_date(now_datetime(), minutes=-10)
	names = []
	for i, (message_type, text, metadata) in enumerate(rows):
		doc = frappe.get_doc({
			"doctype": "Chat Message", "conversation": chat.name, "message_type": message_type,
			"text": text, "metadata": frappe.as_json(metadata) if metadata else None,
		})
		doc.creation = doc.modified = add_to_date(start, seconds=i)
		doc.db_insert()
		names.append(doc.name)
	return chat.name, names


class TestEvalCaseConversation(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite()
		self.mode = frappe.db.get_value("AI Agent Configuration", self.suite.agent_configuration, "chat_mode_label")
		self.chat, self.msgs = _conversation(self.mode, [
			("User", "Visa", None),
			("Bot", "I found Visa. Is that the one?", None),
			("Tool", "__lucrusher_state__", {"intent": "EXACT_MATCH_FOUND"}),
			("User", "yes", None),
			("Bot", "Confirmed. Send the Lucidchart link.", None),
			("Tool", "__lucrusher_state__", {"intent": "CONFIRMED"}),
			("User", "here is the link", None),
		])
		session_state.set_state(self.chat, {"lucid_doc:1": {"title": "Visa Process"}})

	def test_turns_before_the_chosen_message_carry_the_latest_snapshot_before_it(self):
		context = conversation_context_for_case(self.suite.name, self.chat, self.msgs[3])
		messages = context["conversation_messages"]
		self.assertEqual([m["message_type"] for m in messages], ["User", "Bot", "Tool"])
		self.assertEqual(messages[-1]["metadata"], {"intent": "EXACT_MATCH_FOUND"})
		self.assertEqual(context["message_text"], "yes")
		self.assertEqual(context["session_state"], {"lucid_doc:1": {"title": "Visa Process"}})

	def test_through_the_chosen_message_includes_it(self):
		context = conversation_context_for_case(self.suite.name, self.chat, self.msgs[4], include_message=1)
		texts = [m["text"] for m in context["conversation_messages"] if m["message_type"] != "Tool"]
		self.assertEqual(texts[-1], "Confirmed. Send the Lucidchart link.")
		self.assertEqual(context["conversation_messages"][-1]["metadata"], {"intent": "EXACT_MATCH_FOUND"})

	def test_a_message_from_another_conversation_is_refused(self):
		other, other_msgs = _conversation(self.mode, [("User", "hello", None)])
		with self.assertRaises(frappe.ValidationError):
			conversation_context_for_case(self.suite.name, self.chat, other_msgs[0])

	def test_only_user_and_bot_messages_are_listed(self):
		types = {m.message_type for m in get_conversation_for_case(self.suite.name, self.chat)}
		self.assertEqual(types, {"User", "Bot"})

	def test_eval_chats_and_other_agents_are_not_offered(self):
		eval_chat, _ = _conversation(self.mode, [("User", "x", None)], is_eval=1)
		other_agent, _ = _conversation("zz-some-other-agent", [("User", "x", None)])
		names = {c.name for c in list_conversations_for_case(self.suite.name)}
		self.assertIn(self.chat, names)
		self.assertNotIn(eval_chat, names)
		self.assertNotIn(other_agent, names)

	def test_a_user_who_cannot_write_the_suite_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			conversation_context_for_case(self.suite.name, self.chat, self.msgs[3])
