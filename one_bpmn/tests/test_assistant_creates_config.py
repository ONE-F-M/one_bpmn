# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001649: the AI Assistant proposes new agent configurations through chat."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import ai_assistant
from one_bpmn.api.ai_assistant import (
	_creation_prerequisites_block,
	_sanitize_proposed_config,
	recommend_ai_task_config,
)


class TestAssistantCreatesConfig(FrappeTestCase):
	def test_prerequisites_are_live_data(self):
		block = _creation_prerequisites_block()
		# Required fields come from the doctype meta at call time — adding a
		# reqd field to the doctype changes this block with zero code edits.
		for f in frappe.get_meta("AI Agent Configuration").fields:
			if f.reqd:
				self.assertIn(f.fieldname, block)
		# The endpoint contract and validation rules are injected as data.
		self.assertIn("chat_mode_label", block)
		self.assertIn("Validation rules", block)
		# WI-001655: the catalog models (with their credentials) are named.
		for m in frappe.get_all("AI Model", filters={"ai_provider_credentials": ("is", "set")}, pluck="name", limit=3):
			self.assertIn(m, block)

	def test_sanitize_keeps_only_contract_fields(self):
		clean = _sanitize_proposed_config({
			"agent_name": "HR Helper",
			"chat_mode_label": "HR Helper",
			"ai_model": "claude-haiku-4-5-20251001",
			"lifecycle_status": "Live",          # not proposable — dropped
			"agent_type": "Background",          # not proposable — dropped
			"sample_prompts": [
				{"prompt": "hi", "expected_behaviour": "greets"},
				{"prompt": "", "expected_behaviour": "blank dropped"},
				"not-a-dict",
			],
		})
		self.assertEqual(clean["agent_name"], "HR Helper")
		self.assertNotIn("lifecycle_status", clean)
		self.assertNotIn("agent_type", clean)
		self.assertEqual(len(clean["sample_prompts"]), 1)

	def test_sanitize_rejects_junk(self):
		self.assertIsNone(_sanitize_proposed_config(None))
		self.assertIsNone(_sanitize_proposed_config("a string"))
		self.assertIsNone(_sanitize_proposed_config({"unknown": "x"}))

	def test_missing_assistant_record_is_explicit(self):
		# WI-001623/WI-001649: never a hardcoded persona fallback.
		provider = frappe.db.get_value("AI Provider Credentials", {"enabled": 1}, "name")
		if not provider:
			self.skipTest("no enabled AI Provider Credentials on this site")
		original = ai_assistant._assistant_system_prompt
		ai_assistant._assistant_system_prompt = lambda: ""
		try:
			res = recommend_ai_task_config(provider=provider, requirement="anything")
		finally:
			ai_assistant._assistant_system_prompt = original
		self.assertFalse(res["ok"])
		self.assertEqual(res["error_code"], "ASSISTANT_NOT_CONFIGURED")
