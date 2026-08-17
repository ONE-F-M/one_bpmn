# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001649: the AI Assistant proposes new agent configurations through chat."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import ai_assistant
from one_bpmn.api.ai_assistant import (
	_creation_prerequisites_block,
	_extract_json,
	_sanitize_proposed_config,
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
			"agent_type": "Background",          # proposable since the label became Chat-only
			"sample_prompts": [
				{"prompt": "hi", "expected_behaviour": "greets"},
				{"prompt": "", "expected_behaviour": "blank dropped"},
				"not-a-dict",
			],
		})
		self.assertEqual(clean["agent_name"], "HR Helper")
		self.assertNotIn("lifecycle_status", clean)
		# agent_type rides the proposal so a Background (process-embedded)
		# agent is not silently downgraded to Chat, where the label gate fires.
		self.assertEqual(clean["agent_type"], "Background")
		self.assertEqual(len(clean["sample_prompts"]), 1)

	def test_sanitize_keeps_background_proposal_without_creation_process(self):
		# Background agents auto-live on insert — a missing creation process
		# must not suppress their proposal card (it only blocks Chat agents).
		from unittest.mock import patch

		with patch(
			"one_bpmn.agents.agent_config_resolver.get_creation_process_model",
			return_value=None,
		):
			chat = _sanitize_proposed_config({"agent_name": "ZZ Chatty", "chat_mode_label": "ZZ Chatty"})
			background = _sanitize_proposed_config({"agent_name": "ZZ Worker", "agent_type": "Background"})
		self.assertIsNone(chat)
		self.assertIsNotNone(background)
		self.assertEqual(background["agent_type"], "Background")

	def test_sanitize_rejects_junk(self):
		self.assertIsNone(_sanitize_proposed_config(None))
		self.assertIsNone(_sanitize_proposed_config("a string"))
		self.assertIsNone(_sanitize_proposed_config({"unknown": "x"}))

	def test_sanitize_created_config_requires_a_real_record(self):
		# The event is proof of a row, not of the model's claim: a name that
		# resolves nothing (or junk input) yields None — no event, no linking.
		from one_bpmn.api.ai_assistant import _sanitize_created_config

		self.assertIsNone(_sanitize_created_config(None))
		self.assertIsNone(_sanitize_created_config("a string"))
		self.assertIsNone(_sanitize_created_config({"name": ""}))
		self.assertIsNone(_sanitize_created_config({"name": "ZZ Does Not Exist"}))

	def test_sanitize_created_config_reads_agent_id_from_the_record(self):
		from one_bpmn.api.ai_assistant import _sanitize_created_config

		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": "ZZ Created Config Probe",
			"agent_id": "zz_created_config_probe",
			"agent_type": "Background",
			"agent_framework": "Direct API",
		}).insert(ignore_permissions=True)
		clean = _sanitize_created_config({
			"name": doc.name,
			"agent_id": "whatever_the_model_claimed",
		})
		self.assertEqual(clean, {"name": doc.name, "agent_id": "zz_created_config_probe"})

	def test_extract_json_tolerates_literal_newlines_in_strings(self):
		# Models routinely emit raw newlines inside JSON string values —
		# invalid per spec, but strict parsing dropped the whole reply, so
		# the proposed_config was lost and no confirm card rendered (the
		# "Rambo" incident: the user saw raw JSON and no create button).
		raw = (
			'{"message": "Perfect! I have all the details.\n\n'
			'**Agent Name:** Rambo\n**Chat Mode Label:** Rambo_bot",\n'
			'"proposed_config": {"agent_name": "Rambo",'
			' "chat_mode_label": "Rambo_bot"}}'
		)
		parsed = _extract_json(raw)
		self.assertIsInstance(parsed, dict)
		self.assertEqual(parsed["proposed_config"]["agent_name"], "Rambo")
		self.assertIn("Rambo_bot", parsed["message"])

	def test_extract_json_still_handles_fences_and_prose(self):
		self.assertEqual(_extract_json('```json\n{"a": 1}\n```'), {"a": 1})
		self.assertEqual(_extract_json('Sure!\n{"a": "x\ny"}\nHope that helps.'), {"a": "x\ny"})
		self.assertIsNone(_extract_json("no json here"))
		self.assertIsNone(_extract_json(""))

	def test_the_dialogs_private_chat_endpoint_stays_retired(self):
		"""WI-001679: recommend_ai_task_config was this dialog's own chat door.

		It also carried the ASSISTANT_NOT_CONFIGURED guard that this case used
		to pin — the guard against a hardcoded persona fallback (WI-001623).
		That property is structural now rather than checked: both dialog modes
		run on the assistant's own configuration through the shared stream, so
		there is no code path left that could substitute a persona. What is
		worth pinning is that the private door does not come back, because a
		re-added endpoint quietly rebuilds the fragmentation this epic removed.
		"""
		self.assertFalse(hasattr(ai_assistant, "recommend_ai_task_config"))
