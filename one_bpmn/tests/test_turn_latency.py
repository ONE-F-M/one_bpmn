# Copyright (c) 2026, one-fm and contributors
"""Per-turn latency: model time is stored apart from tool time, a model call
made inside a tool is not counted twice on the run, and the AI Turn Latency
report splits a run into queue, engine, model, model-in-tools and tool time.

    bench run-tests --skip-before-tests --module one_bpmn.tests.test_turn_latency
"""

import asyncio
import time
from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec
from one_bpmn.agents.observability import _sum_step_metrics, record_ai_step
from one_bpmn.one_bpmn.report.ai_turn_latency.ai_turn_latency import break_down

T0 = datetime(2026, 10, 1, 10, 0, 0)


def at(ms):
	return T0 + timedelta(milliseconds=ms)


def step(kind, start_ms, end_ms, latency_ms, model_latency_ms=0):
	return frappe._dict(
		step_kind=kind,
		started_at=at(start_ms),
		ended_at=at(end_ms),
		latency_ms=latency_ms,
		model_latency_ms=model_latency_ms,
	)


class SlowAdapter:
	def __init__(self, steps):
		self.steps = list(steps)

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		await asyncio.sleep(0.03)
		return self.steps.pop(0)


class TestModelTimeIsStoredApart(FrappeTestCase):
	def test_a_tool_turn_keeps_model_time_out_of_tool_time(self):
		def slow_tool(**kwargs):
			time.sleep(0.06)
			return "done"

		adapter = SlowAdapter([
			StepResult(content="", tool_calls=[StepToolCall(id="c1", name="lookup", arguments={})]),
			StepResult(content="answer"),
		])
		result, _suspension = asyncio.run(
			run_agent_loop(
				adapter,
				system="sys",
				user="go",
				tools=[ToolSpec(fn=slow_tool, name="lookup", description="a read")],
				max_tokens=100,
				max_turns=5,
			)
		)
		tool_turn, final_turn = result.trace
		self.assertGreaterEqual(tool_turn.model_latency_ms, 30)
		self.assertGreaterEqual(tool_turn.latency_ms - tool_turn.model_latency_ms, 60)
		self.assertLess(final_turn.latency_ms - final_turn.model_latency_ms, 30)


class TestRunLatencyCountsEachMillisecondOnce(FrappeTestCase):
	def test_a_sub_call_inside_a_tool_is_not_added_on_top_of_its_turn(self):
		run = frappe.get_doc({
			"doctype": "AI Agent Run",
			"bpmn_id": "latency_probe",
			"status": "Running",
			"started_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
		record_ai_step(run, 1, "tool", "", latency_ms=1000, tool_calls=[{"name": "lookup"}])
		record_ai_step(run, 2, "assistant", "[sub-call: lookup via m; turn 1]\nx", latency_ms=400)
		record_ai_step(run, 3, "assistant", "[sub-call: compaction via m]\nsummary", latency_ms=150)

		self.assertEqual(_sum_step_metrics(run.name)["agent_latency_ms"], 1150)


class TestTheReportSplitsARun(FrappeTestCase):
	def run_doc(self):
		return frappe._dict(
			name="run-1", started_at=T0, duration_ms=2500, human_wait_ms=0, queue_wait_ms=80
		)

	def test_each_turn_and_the_run_are_split_by_where_time_went(self):
		steps = [
			step("prompt", 0, 0, 0),
			step("tool_turn", 100, 1100, 1000, 300),
			step("sub_call", 500, 900, 400),
			step("sub_call", 1150, 1300, 150),
			step("model_call", 1400, 1900, 500, 500),
		]

		run_row, (first, second) = break_down(self.run_doc(), steps)

		self.assertEqual(
			(first["engine_ms"], first["model_ms"], first["tool_llm_ms"], first["tool_ms"]),
			(100, 300, 400, 300),
		)
		self.assertEqual((second["engine_ms"], second["model_ms"], second["tool_ms"]), (300, 500, 0))
		self.assertEqual(
			(run_row["queue_ms"], run_row["engine_ms"], run_row["model_ms"], run_row["tool_ms"]),
			(80, 850, 950, 300),
		)

	def test_a_turn_recorded_without_model_time_is_shown_as_unknown(self):
		run_row, (turn,) = break_down(self.run_doc(), [step("tool_turn", 0, 700, 700)])

		self.assertIsNone(turn["model_ms"])
		self.assertIsNone(turn["tool_ms"])
		self.assertIsNone(run_row["model_ms"])
