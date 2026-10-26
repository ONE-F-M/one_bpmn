# Copyright (c) 2026, one-fm and contributors
"""Memory settings on a chat agent with no Process Model do nothing.

Recall and writeback run in the map dispatcher. Without a map the agent takes
the single-shot path, which never reads a memory and never writes one, while
the form goes on showing Long-Term Memory as Enabled. On staging that cost an
afternoon: the settings were right, the agent remembered nothing, and there was
nothing anywhere to connect the two.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


def _config(**fields):
	doc = frappe.new_doc("AI Agent Configuration")
	doc.update({"long_term_memory": "Enabled", "agent_type": "Chat", **fields})
	return doc


class TestMemoryNeedsAMap(FrappeTestCase):
	def _warnings(self, doc) -> list[str]:
		with patch.object(frappe, "msgprint") as msgprint:
			doc.warn_if_memory_has_no_map()
		return [str(call.args[0]) for call in msgprint.call_args_list]

	def test_a_chat_agent_with_no_map_is_told(self):
		said = self._warnings(_config(process_model=None))
		self.assertEqual(len(said), 1)
		self.assertIn("Process Model", said[0])

	def test_a_chat_agent_with_a_map_is_left_alone(self):
		self.assertEqual(self._warnings(_config(process_model="Some Chat Map")), [])

	def test_a_background_agent_is_left_alone(self):
		"""It is invoked by a record, and it carries no map of its own."""
		self.assertEqual(self._warnings(_config(agent_type="Background", process_model=None)), [])

	def test_memory_left_blank_warns_about_nothing(self):
		"""Blank means inherit the diagram's value, which the form does not decide."""
		doc = _config(long_term_memory=None, process_model=None)
		with patch.object(frappe, "msgprint") as msgprint:
			doc.validate_memory_config()
		msgprint.assert_not_called()
