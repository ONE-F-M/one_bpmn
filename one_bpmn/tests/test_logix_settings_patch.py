"""The Logix settings patch bounds context and output, sets timeouts, and aligns the Cost & Tokens guard rail with the modifying skill."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_settings_are_bounded_and_match_its_skills as patch

OLD_RULE = "Check token usage: do not echo an entire script back when a diff would do."
OTHER_RULE = "Keep every script you write under 300 lines."


class TestLogixSettingsPatch(FrappeTestCase):
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

	def _run(self, settings, guardrail_agent=None):
		with (
			mock.patch.object(patch, "SETTINGS", settings),
			mock.patch.object(patch, "GUARDRAIL_AGENT", guardrail_agent),
		):
			patch.execute()

	def _value(self, doc, field):
		return frappe.db.get_value("AI Agent Configuration", doc.name, field)

	def test_each_agent_gets_its_values(self):
		chat = self._config(context_max_messages=224, temperature=0.7)
		writer = self._config(max_tokens=4096)
		tester = self._config(max_tokens=1024, timeout_seconds=0, max_retries=0)
		settings = {
			chat.agent_id: {"context_max_messages": 20, "temperature": 0},
			writer.agent_id: {"max_tokens": 8192},
			tester.agent_id: {"max_tokens": 2048, "timeout_seconds": 60, "max_retries": 2},
		}
		self._run(settings)
		self.assertEqual(self._value(chat, "context_max_messages"), 20)
		self.assertEqual(self._value(chat, "temperature"), 0)
		self.assertEqual(self._value(writer, "max_tokens"), 8192)
		self.assertEqual(
			[self._value(tester, f) for f in ("max_tokens", "timeout_seconds", "max_retries")], [2048, 60, 2]
		)

	def test_cost_and_tokens_rule_is_replaced_and_others_kept(self):
		chat = self._config(
			guardrails=[
				{"category": "Cost & Tokens", "guardrail": OLD_RULE, "enabled": 1},
				{"category": "Code Quality", "guardrail": OTHER_RULE, "enabled": 1},
			]
		)
		self._run({chat.agent_id: {"context_max_messages": 20}}, guardrail_agent=chat.agent_id)
		rules = {r.category: r.guardrail for r in frappe.get_doc("AI Agent Configuration", chat.name).guardrails}
		self.assertEqual(rules, {"Cost & Tokens": patch.GUARDRAIL, "Code Quality": OTHER_RULE})

	def test_guardrail_agrees_with_the_full_script_skill(self):
		self.assertIn("full script", patch.GUARDRAIL)
		self.assertNotIn("echo", patch.GUARDRAIL.lower())

	def test_second_run_changes_nothing(self):
		chat = self._config(guardrails=[{"category": "Cost & Tokens", "guardrail": OLD_RULE, "enabled": 1}])
		settings = {chat.agent_id: {"context_max_messages": 20}}
		self._run(settings, guardrail_agent=chat.agent_id)
		self._run(settings, guardrail_agent=chat.agent_id)
		doc = frappe.get_doc("AI Agent Configuration", chat.name)
		self.assertEqual([r.guardrail for r in doc.guardrails], [patch.GUARDRAIL])
		self.assertEqual(doc.context_max_messages, 20)

	def test_absent_agent_is_skipped(self):
		self._run({"no_such_agent": {"max_tokens": 8192}})
