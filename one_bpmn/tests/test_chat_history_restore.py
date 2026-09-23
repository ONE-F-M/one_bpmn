# Copyright (c) 2026, one-fm and contributors
"""What a reopened conversation gets back.

A reply's cards and option buttons were built from the result the turn
produced, and that result is saved beside the text. Until now the history
endpoint returned the text alone, so reloading a page turned a proposal panel
into a paragraph.

The events are rebuilt by replaying the same translators the live stream uses,
so these tests are mostly about the ways that replay can go wrong: metadata
that was never written, metadata that is not a reply, and a page boundary that
has to be crossed without losing or repeating a message.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.agui import conversation_history
from one_bpmn.utils.chat_persistence import (
	create_conversation,
	load_history,
	save_bot_message,
	save_user_message,
)


def _remove(conversation: str) -> None:
	"""Saving a message commits, so the framework's rollback does not reach
	these — without this the site collects a conversation per test run."""
	for name in frappe.get_all("Chat Message", filters={"conversation": conversation}, pluck="name"):
		frappe.db.delete("Chat Message", {"name": name})
	frappe.db.delete("Chat Conversation", {"name": conversation})
	frappe.db.commit()

CHOICE = {
	"agent_result": {
		"intent": "CONFIRM",
		"response": "Apply this topology?",
		"options": ["Yes, proceed", "No, let me adjust"],
		"action_intent": "APPLY_TOPOLOGY",
	}
}


class TestHistoryCarriesEvents(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = create_conversation("prosally", "_Test restore", frappe.session.user)

	def tearDown(self):
		_remove(self.conversation)

	def test_a_reply_that_asked_a_question_asks_it_again(self):
		save_user_message(self.conversation, "draw me a process")
		save_bot_message(self.conversation, "Apply this topology?", metadata=CHOICE)

		history = conversation_history(self.conversation)
		reply = history[-1]
		self.assertEqual(reply["role"], "assistant")
		self.assertEqual([e["name"] for e in reply["events"]], ["onefm.choice"])
		self.assertEqual(
			reply["events"][0]["value"]["options"], ["Yes, proceed", "No, let me adjust"]
		)
		self.assertEqual(reply["events"][0]["value"]["action_intent"], "APPLY_TOPOLOGY")

	def test_a_plain_reply_carries_no_events(self):
		save_bot_message(self.conversation, "Here is the answer.")
		self.assertEqual(conversation_history(self.conversation)[-1]["events"], [])

	def test_a_user_message_never_carries_events(self):
		save_user_message(self.conversation, "hello")
		self.assertEqual(conversation_history(self.conversation)[0]["events"], [])

	def test_metadata_that_is_not_a_reply_is_ignored(self):
		"""Turns store other things here too; only a result becomes events."""
		save_bot_message(self.conversation, "done", metadata={"intent": "GREET"})
		self.assertEqual(conversation_history(self.conversation)[-1]["events"], [])

	def test_unreadable_metadata_still_shows_the_words(self):
		name = save_bot_message(self.conversation, "the reply text")
		frappe.db.set_value("Chat Message", name, "metadata", "{not json", update_modified=False)
		reply = conversation_history(self.conversation)[-1]
		self.assertEqual(reply["content"], "the reply text")
		self.assertEqual(reply["events"], [])

	def test_a_broken_translator_cannot_empty_the_transcript(self):
		"""One event type failing must not cost the reply its text."""
		save_bot_message(self.conversation, "still here", metadata={"agent_result": {"intent": None}})
		self.assertEqual(conversation_history(self.conversation)[-1]["content"], "still here")

    # metadata is an implementation detail of the store, not of the transcript
	def test_the_endpoint_does_not_hand_back_raw_metadata(self):
		save_bot_message(self.conversation, "Apply this topology?", metadata=CHOICE)
		self.assertNotIn("metadata", conversation_history(self.conversation)[-1])


class TestPaging(FrappeTestCase):
	"""A conversation longer than one page has to be reachable."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = create_conversation("prosally", "_Test paging", frappe.session.user)
		for index in range(12):
			save_user_message(self.conversation, f"q{index}")
			save_bot_message(self.conversation, f"a{index}")

	def tearDown(self):
		_remove(self.conversation)

	def test_the_newest_page_comes_back_first(self):
		page = conversation_history(self.conversation, limit=10)
		self.assertEqual(len(page), 10)
		self.assertEqual(page[-1]["content"], "a11", "the newest message ends the page")

	def test_older_messages_are_reachable_through_the_cursor(self):
		newest = conversation_history(self.conversation, limit=10)
		older = conversation_history(self.conversation, limit=10, before=newest[0]["message"])
		self.assertTrue(older)
		self.assertLess(
			older[-1]["timestamp"], newest[0]["timestamp"], "a page ends where the next begins"
		)

	def test_a_page_boundary_repeats_nothing(self):
		newest = conversation_history(self.conversation, limit=10)
		older = conversation_history(self.conversation, limit=10, before=newest[0]["message"])
		self.assertFalse(
			{m["message"] for m in newest} & {m["message"] for m in older},
			"a message must not appear on two pages",
		)

	def test_the_whole_conversation_is_reachable(self):
		seen, cursor = [], None
		for _page in range(6):
			page = conversation_history(self.conversation, limit=10, before=cursor)
			if not page:
				break
			seen = page + seen
			cursor = page[0]["message"]
		self.assertEqual(len(seen), 24, "12 questions and 12 answers")

	def test_a_cursor_that_has_gone_reads_as_no_cursor(self):
		"""A deleted message must not strand the reader on an error."""
		page = conversation_history(self.conversation, limit=5, before="no-such-message")
		self.assertEqual(len(page), 5)

	def test_the_end_of_the_conversation_is_an_empty_page(self):
		oldest = load_history(self.conversation, limit=100)[0]
		self.assertEqual(conversation_history(self.conversation, before=oldest["message"]), [])


class TestHistoryCarriesWorkingNotes(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = create_conversation("lumina_general_chat", "_Test notes", frappe.session.user)
		self.instances = [self._instance(self.conversation), self._instance("ZZ-OTHER-CONV")]

	def tearDown(self):
		runs = frappe.get_all("AI Agent Run", filters={"instance": ["in", self.instances]}, pluck="name")
		frappe.db.delete("AI Agent Step", {"run": ["in", runs or [""]]})
		frappe.db.delete("AI Agent Run", {"name": ["in", runs or [""]]})
		frappe.db.delete("BPMN Process Instance", {"name": ["in", self.instances]})
		_remove(self.conversation)

	def _instance(self, conversation):
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"notes-{frappe.generate_hash(length=6)}",
				"status": "Active",
				"context_doctype": "Chat Conversation",
				"context_docname": conversation,
			}
		)
		instance.flags.ignore_mandatory = True
		instance.flags.ignore_links = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		return instance.name

	def _run(self, instance, said):
		run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": instance,
				"bpmn_id": "run_general_chat_agent",
				"status": "Success",
				"started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		for index, content in enumerate(said, start=3):
			frappe.get_doc(
				{"doctype": "AI Agent Step", "run": run.name, "step_index": index, "role": "tool", "content": content}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "AI Agent Step", "run": run.name, "step_index": 9, "role": "assistant", "content": "the reply"}
		).insert(ignore_permissions=True)
		return run

	def test_each_reply_gets_the_notes_of_its_own_turn(self):
		save_user_message(self.conversation, "add 2 and 3, then 10")
		self._run(self.instances[0], ["Step 1: adding 2 + 3", "Step 2: adding 5 + 10"])
		self._run(self.instances[1], ["someone else's turn"])
		save_bot_message(self.conversation, "15")
		save_user_message(self.conversation, "thanks")
		save_bot_message(self.conversation, "you're welcome")

		history = conversation_history(self.conversation)
		self.assertEqual(history[1]["notes"], ["Step 1: adding 2 + 3", "Step 2: adding 5 + 10"])
		self.assertEqual(history[3]["notes"], [])
		self.assertEqual(history[0]["notes"], [])

	def test_blank_tool_steps_are_not_notes(self):
		save_user_message(self.conversation, "count ToDo")
		self._run(self.instances[0], ["", "   "])
		save_bot_message(self.conversation, "352,794")
		self.assertEqual(conversation_history(self.conversation)[-1]["notes"], [])
