# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""An agent with no enabled skill is not offered load_skill, unload_skill or load_skill_resource.

Checked on the tool list dispatch_ai_agent hands the executor.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage

SKILL_TOOL_NAMES = {"load_skill", "unload_skill", "load_skill_resource"}


class TestSkillToolDispatchGating(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.bpmn_id = "Agent_1"
		self.task = frappe._dict(
			{"data": {}, "task_spec": frappe._dict({"name": self.bpmn_id, "description": "Agent"})}
		)
		self._docs_to_delete = []

	def tearDown(self):
		for doctype, name in reversed(self._docs_to_delete):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _make_agent_config(self, enabled_skill_names=None):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": f"_Test Skill Gating {frappe.generate_hash(length=6)}",
				"agent_id": f"_test_skill_gating_{frappe.generate_hash(length=6)}",
				"agent_framework": "LangGraph",
				"enabled": 1,
				"system_prompt": "You are a test agent.",
				"enabled_skills": [{"skill": name} for name in (enabled_skill_names or [])],
			}
		)
		doc.insert(ignore_permissions=True)
		self._docs_to_delete.append(("AI Agent Configuration", doc.name))
		return doc

	def _make_active_skill(self):
		skill = frappe.get_doc(
			{
				"doctype": "AI Skill",
				"skill_name": frappe.generate_hash(length=8),
				"status": "Active",
				"tier": "Draft-Only",
				"description": "Use this skill when testing dispatch gating; do not use otherwise.",
				"body": "Some instructions for the agent.",
			}
		)
		skill.insert(ignore_permissions=True)
		self._docs_to_delete.append(("AI Skill", skill.name))
		return skill

	def _dispatch(self, task_cfg, result):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		captured = {}

		def fake_run(_self, config, context):
			captured["config"] = config
			return result

		with (
			patch("one_bpmn.agents.model_health.refuse_new_run", return_value=None),
			patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run),
		):
			dispatchers.dispatch_ai_agent(self.instance, self.task, task_cfg, self.bpmn_id)
		return captured

	def _tool_names(self, captured):
		tools = captured["config"].tools or []
		return {t.name for t in tools}

	def test_no_enabled_skills_means_no_skill_tools_in_the_dispatched_list(self):
		agent = self._make_agent_config(enabled_skill_names=[])
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "hi",
			"aiOutputVariable": "agent_out",
			"aiAgentConfig": agent.name,
		}
		result = ExecutorResult(
			output="hi",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
		)
		captured = self._dispatch(task_cfg, result)
		names = self._tool_names(captured)
		self.assertFalse(names & SKILL_TOOL_NAMES, f"no skill tools expected, got {names}")

	def test_an_enabled_skill_puts_all_three_skill_tools_in_the_dispatched_list(self):
		skill = self._make_active_skill()
		agent = self._make_agent_config(enabled_skill_names=[skill.name])
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "hi",
			"aiOutputVariable": "agent_out",
			"aiAgentConfig": agent.name,
		}
		result = ExecutorResult(
			output="hi",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
		)
		captured = self._dispatch(task_cfg, result)
		names = self._tool_names(captured)
		self.assertTrue(SKILL_TOOL_NAMES <= names, f"expected all skill tools, got {names}")
