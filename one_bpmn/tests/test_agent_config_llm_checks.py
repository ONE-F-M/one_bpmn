# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Save checks on the agent configuration's Thinking Budget Tokens and Tool Choice."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase


def _config(name: str = "ZZ Tool Choice Test Agent", **fields):
	return frappe.get_doc({"doctype": "AI Agent Configuration", "name": name, "agent_name": name, **fields})


def _deployed_map(title: str, config_name: str, tools: list[str]):
	spec = {
		"service_task_extensions": {
			"run_agent": {
				"serviceType": "ai_agent",
				"aiAgentConfig": config_name,
				"aiToolShapes": json.dumps([{"bpmn_id": t} for t in tools]),
			}
		}
	}
	frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"name": title,
			"title": title,
			"process_id": frappe.generate_hash(length=10),
			"serialized_spec": json.dumps(spec),
		}
	).db_insert()


class TestThinkingBudgetMessage(FrappeTestCase):
	def test_a_max_tokens_too_small_for_thinking_says_to_raise_it(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_config(max_tokens=1024, thinking_budget_tokens=1024).validate_thinking_budget()
		self.assertIn("Max Tokens must be above 1,024", str(ctx.exception))
		self.assertIn("raise Max Tokens", str(ctx.exception))

	def test_a_budget_over_max_tokens_names_the_highest_allowed_value(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_config(max_tokens=4096, thinking_budget_tokens=5000).validate_thinking_budget()
		self.assertIn("between 1,024 and 4,095", str(ctx.exception))

	def test_a_budget_inside_the_range_passes(self):
		_config(max_tokens=4096, thinking_budget_tokens=2048).validate_thinking_budget()


class TestToolChoiceCheck(FrappeTestCase):
	def setUp(self):
		# Rows inserted here outlive a single test, so each test gets its own agent and map names.
		self.agent = f"ZZ Tool Choice Agent {frappe.generate_hash(length=6)}"

	def _map(self, label: str, tools: list[str], agent: str | None = None) -> str:
		title = f"{self.agent} {label}"
		_deployed_map(title, agent or self.agent, tools)
		return title

	def test_auto_required_and_blank_need_no_map(self):
		for choice in ("", "auto", "required"):
			_config(self.agent, tool_choice=choice).validate_tool_choice()

	def test_a_tool_on_every_deployed_map_passes(self):
		self._map("Map A", ["classify_intent", "finalize"])
		self._map("Map B", ["classify_intent"])
		_config(self.agent, tool_choice="classify_intent").validate_tool_choice()

	def test_a_tool_missing_from_one_map_is_refused_and_names_that_map(self):
		map_a = self._map("Map A", ["classify_intent", "finalize"])
		map_b = self._map("Map B", ["classify_intent"])
		with self.assertRaises(frappe.ValidationError) as ctx:
			_config(self.agent, tool_choice="finalize").validate_tool_choice()
		self.assertIn(map_b, str(ctx.exception))
		self.assertNotIn(map_a, str(ctx.exception))

	def test_a_typo_is_refused(self):
		self._map("Map A", ["classify_intent"])
		with self.assertRaises(frappe.ValidationError):
			_config(self.agent, tool_choice="clasify_intent").validate_tool_choice()

	def test_a_tool_name_with_no_deployed_map_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_config(self.agent, tool_choice="classify_intent").validate_tool_choice()
		self.assertIn("no deployed map runs this agent", str(ctx.exception))

	def test_a_map_for_another_agent_does_not_count(self):
		self._map("Other Map", ["classify_intent"], agent=f"{self.agent} Other")
		with self.assertRaises(frappe.ValidationError):
			_config(self.agent, tool_choice="classify_intent").validate_tool_choice()
