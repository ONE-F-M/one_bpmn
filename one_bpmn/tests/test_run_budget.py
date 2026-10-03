# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A run stops with BUDGET_EXCEEDED once it passes its token or cost budget, edit or not."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import goal_completion, shape_tools
from one_bpmn.agents.agent_config_resolver import config_field_map
from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec
from one_bpmn.agents.shape_tools import BudgetExceeded

RATES = {
	"input_cost_per_1k": 0.003,
	"output_cost_per_1k": 0.015,
	"cache_read_cost_per_1k": 0.0003,
	"cache_write_cost_per_1k": 0.00375,
}


def _provider(name):
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(ignore_permissions=True)
	return name


def _model(name):
	if not frappe.db.exists("AI Model", name):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"provider": _provider("Anthropic"),
				"enable_model": 1,
				"api_key": "test-key-not-real",
			}
		).insert(ignore_permissions=True)
	return name


class _ToolLoopAdapter:
	"""Asks for one more read every turn, 10k prompt and 1k completion tokens each time."""

	def __init__(self):
		self.calls = 0

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.calls += 1
		return StepResult(
			content="",
			tool_calls=[StepToolCall(id=f"c{self.calls}", name="read_file", arguments={"path": "a.py"})],
			prompt_tokens=10_000,
			completion_tokens=1_000,
		)


def _read_file(fn=None):
	return ToolSpec(
		fn=fn or (lambda **kw: "contents"),
		name="read_file",
		description="Read a file.",
		parameters={"path": {"type": "string", "description": "Path"}},
		required=["path"],
	)


class TestTheLoopStopsAtTheBudget(FrappeTestCase):
	def _run(self, tool=None, **budgets):
		config = ExecutorConfig(
			provider_name=_provider("Anthropic"),
			model=_model("_budget-model"),
			system_prompt="sys",
			user_prompt="usr",
			tools=[tool or _read_file()],
			max_tool_calls=20,
			**budgets,
		)
		adapter = _ToolLoopAdapter()
		with (
			patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=adapter),
			patch("one_bpmn.agents.pricing.get_model_pricing", return_value=RATES),
		):
			result = DirectApiExecutor().run(config, ExecutorContext())
		return result, adapter

	def test_a_token_budget_stops_the_run_and_names_the_last_tool(self):
		result, adapter = self._run(run_token_budget=25_000)

		self.assertEqual(result.error_code, ErrorCode.BUDGET_EXCEEDED)
		self.assertEqual(adapter.calls, 3)
		self.assertIn("token budget of 25,000 with 33,000 tokens", result.error_message)
		self.assertIn("Last tool called: read_file", result.error_message)

	def test_a_cost_budget_stops_the_run(self):
		# Each turn costs 10k x 0.003/1k + 1k x 0.015/1k = $0.045.
		result, adapter = self._run(run_cost_budget=0.10)

		self.assertEqual(result.error_code, ErrorCode.BUDGET_EXCEEDED)
		self.assertEqual(adapter.calls, 3)
		self.assertIn("cost budget of $0.10 at $0.14", result.error_message)

	def test_no_budget_runs_to_the_turn_cap(self):
		result, adapter = self._run()

		self.assertEqual(result.error_code, ErrorCode.TURN_CAP_REACHED)
		self.assertEqual(adapter.calls, 20)

	def test_a_tool_that_raises_budget_exceeded_ends_the_run(self):
		def refuse(**kw):
			raise BudgetExceeded("the run kept reading after it was told to stop")

		result, adapter = self._run(tool=_read_file(refuse))

		self.assertEqual(result.error_code, ErrorCode.BUDGET_EXCEEDED)
		self.assertEqual(adapter.calls, 1)
		self.assertIn("kept reading after it was told to stop (in read_file)", result.error_message)


class TestBudgetExceededReachesTheLoop(FrappeTestCase):
	def test_execute_shape_lets_it_through(self):
		instance = SimpleNamespace(name="_budget-instance", context_doctype="", context_docname="")
		with (
			patch.object(shape_tools, "_execute_shape_body", side_effect=BudgetExceeded("spent")),
			patch.object(shape_tools, "_announce"),
			self.assertRaises(BudgetExceeded),
		):
			shape_tools.execute_shape(instance, "read_file", {}, {})


class TestTheRunRecordsWhy(FrappeTestCase):
	def test_the_basis_quotes_the_budget_and_the_last_tool(self):
		result = SimpleNamespace(
			error_code=ErrorCode.BUDGET_EXCEEDED,
			error_message="The run passed its cost budget of $1.50 at $1.62. Last tool called: read_file.",
			hit_turn_cap=False,
			output=None,
		)
		state, basis = goal_completion.determine(result)

		self.assertEqual(state, goal_completion.NOT_ACHIEVED)
		self.assertIn("cost budget of $1.50", basis)
		self.assertIn("read_file", basis)


class TestTheBudgetsReachTheShape(FrappeTestCase):
	def test_set_budgets_map_and_blank_ones_do_not(self):
		cfg = frappe._dict(run_token_budget=1_500_000, run_cost_budget=1.5)
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=cfg):
			out = config_field_map("_budget-config")
		self.assertEqual(out["aiRunTokenBudget"], 1_500_000)
		self.assertEqual(out["aiRunCostBudget"], 1.5)

		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", return_value=frappe._dict()),
		):
			out = config_field_map("_budget-config")
		self.assertNotIn("aiRunTokenBudget", out)
		self.assertNotIn("aiRunCostBudget", out)
