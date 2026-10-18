"""New inference and tool-output memories expire after 30 days; Docu and Logix memory is personal."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_datetime, now_datetime

from one_bpmn.agents.memory.tools import MEMORY_TTL_DAYS, memory_write
from one_bpmn.one_bpmn.patches.v1_0 import docu_and_logix_memory_is_personal as patch


class TestMemoryExpiry(FrappeTestCase):
	def _write(self, source_type=None, **kw):
		key = {"agent_element": f"Act_{frappe.generate_hash(length=6)}"}
		row = memory_write("Agent", key, "a fact", source_type=source_type, ignore_permissions=True, **kw)
		return frappe.db.get_value("AI Memory", row["name"], "expires_on")

	def test_inference_and_tool_output_expire_in_30_days(self):
		for source_type in ("Agent Inference", "Tool Output", None):
			expires = get_datetime(self._write(source_type))
			due = get_datetime(add_days(now_datetime(), MEMORY_TTL_DAYS))
			self.assertLess(abs((expires - due).total_seconds()), 60)

	def test_a_user_statement_does_not_expire(self):
		self.assertIsNone(self._write("User Statement"))


class TestPersonalMemoryPatch(FrappeTestCase):
	def _config(self, **fields):
		agent_id = f"t_{frappe.generate_hash(length=8)}"
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": agent_id,
				"agent_id": agent_id,
				"agent_framework": "Direct API",
				"agent_type": "Chat",
				**fields,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_scope_is_personal_and_sub_agents_keep_no_memory(self):
		chat = self._config(memory_scope="Agent")
		sub = self._config(agent_type="Background")
		with (
			mock.patch.object(patch, "PERSONAL", (chat.agent_id,)),
			mock.patch.object(patch, "NO_MEMORY", (sub.agent_id,)),
		):
			patch.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", chat.name, "memory_scope"), "User and Agent")
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", sub.name, "long_term_memory"), "Disabled")
