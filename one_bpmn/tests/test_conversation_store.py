# Copyright (c) 2026, one-fm and contributors
# Tests for the conversation store: all three backends, per-task isolation,
# and context-window trimming with system-prompt retention.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.conversation_store import (
	ContextWindowPolicy,
	ProcessVariableStore,
	get_conversation_store,
)


class TestProcessVariableStore(FrappeTestCase):
	def test_round_trip_and_isolation(self):
		task = SimpleNamespace(data={})
		store = get_conversation_store("process_variable", task=task)
		store.append("I", "A", {"role": "user", "content": "hi"})
		store.append("I", "A", {"role": "assistant", "content": "yo"})
		store.append("I", "B", {"role": "user", "content": "other"})
		self.assertEqual([m["role"] for m in store.load("I", "A")], ["user", "assistant"])
		self.assertEqual(store.load("I", "A")[0]["content"], "hi")
		# two bpmn_ids never share a thread
		self.assertEqual(len(store.load("I", "B")), 1)
		self.assertIn("A_conversation", task.data)

	def test_requires_live_task(self):
		with self.assertRaises(frappe.ValidationError):
			get_conversation_store("process_variable").load("I", "A")


class TestDocumentStore(FrappeTestCase):
	def test_field_mapping_and_order(self):
		store = get_conversation_store("document_store")
		store.append("I9", "X", {"role": "system", "content": "sys"})
		store.append("I9", "X", {"role": "assistant", "content": "call", "tool_calls": [{"id": "c1"}]})
		store.append("I9", "X", {"role": "tool", "content": "res", "tool_call_id": "c1"})

		msgs = store.load("I9", "X")
		self.assertEqual([m["role"] for m in msgs], ["system", "assistant", "tool"])
		self.assertEqual(msgs[1]["tool_calls"], [{"id": "c1"}])
		self.assertEqual(msgs[2]["tool_call_id"], "c1")

		# onefm_mcp records created with the documented mapping
		conv = frappe.db.get_value("Chat Conversation", {"title": "one_bpmn:I9:X"}, "name")
		self.assertTrue(conv)
		rows = frappe.get_all(
			"Chat Message", filters={"conversation": conv}, fields=["message_type", "text"]
		)
		self.assertEqual(len(rows), 3)
		# role -> message_type: assistant -> Bot, content -> text
		self.assertIn(("Bot", "call"), [(r["message_type"], r["text"]) for r in rows])

	def test_thread_isolation(self):
		store = get_conversation_store("document_store")
		store.append("I9", "X", {"role": "user", "content": "x"})
		store.append("I9", "Y", {"role": "user", "content": "y"})
		self.assertEqual([m["content"] for m in store.load("I9", "Y")], ["y"])


class TestCustomStore(FrappeTestCase):
	def test_missing_hook_raises(self):
		with patch("frappe.get_hooks", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				get_conversation_store("custom")

	def test_hook_resolution(self):
		path = "one_bpmn.agents.memory.conversation_store.ProcessVariableStore"
		with patch("frappe.get_hooks", return_value=[path]):
			store = get_conversation_store("custom")
		self.assertIsInstance(store, ProcessVariableStore)


class TestContextWindowPolicy(FrappeTestCase):
	def test_trims_and_retains_system(self):
		policy = ContextWindowPolicy(max_messages=3)
		thread = [{"role": "system", "content": "S"}] + [
			{"role": "user", "content": str(i)} for i in range(10)
		]
		out = policy.apply(thread)
		self.assertEqual(len(out), 3)
		self.assertEqual(out[0]["role"], "system")  # system always retained, first
		self.assertEqual(out[-1]["content"], "9")    # most recent kept

	def test_no_trim_when_within_limit(self):
		policy = ContextWindowPolicy(max_messages=5)
		thread = [{"role": "user", "content": "a"}]
		self.assertEqual(policy.apply(thread), thread)

	def test_policy_applied_on_load(self):
		task = SimpleNamespace(data={})
		store = get_conversation_store("process_variable", task=task, policy=ContextWindowPolicy(2))
		for i in range(5):
			store.append("I", "B", {"role": "user", "content": str(i)})
		self.assertEqual([m["content"] for m in store.load("I", "B")], ["3", "4"])
