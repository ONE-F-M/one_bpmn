# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAISkill(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _make_skill(self, description):
		return frappe.get_doc({
			"doctype": "AI Skill",
			"skill_name": frappe.generate_hash(length=8),
			"status": "Draft",
			"tier": "Draft-Only",
			"description": description,
			"body": "Some instructions for the agent.",
		})

	def _mock_adapter(self, content):
		adapter = MagicMock()

		async def _step(**kwargs):
			return frappe._dict(content=content)

		adapter.step.side_effect = _step
		return adapter

	def test_ambiguous_description_shows_ai_suggestion_but_still_saves(self):
		skill = self._make_skill("Handles stuff sometimes.")
		adapter = self._mock_adapter(json.dumps({
			"clear": False,
			"suggestion": "Use this skill when doing X; do not use it for Y.",
		}))
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter_from_settings",
			return_value=adapter,
		):
			with patch("frappe.msgprint") as mock_msgprint:
				skill.insert(ignore_permissions=True)
				self.assertTrue(mock_msgprint.called)
		self.assertTrue(frappe.db.exists("AI Skill", skill.name))

	def test_clear_description_saves_without_suggestion(self):
		skill = self._make_skill("Use this skill when reviewing swimlanes; do not use it otherwise.")
		adapter = self._mock_adapter(json.dumps({"clear": True}))
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter_from_settings",
			return_value=adapter,
		):
			with patch("frappe.msgprint") as mock_msgprint:
				skill.insert(ignore_permissions=True)
				self.assertFalse(mock_msgprint.called)

	def test_ai_review_failure_never_blocks_save(self):
		skill = self._make_skill("Anything goes here, no magic phrases at all.")
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter_from_settings",
			side_effect=RuntimeError("no provider configured"),
		):
			skill.insert(ignore_permissions=True)  # must not raise
		self.assertTrue(frappe.db.exists("AI Skill", skill.name))
