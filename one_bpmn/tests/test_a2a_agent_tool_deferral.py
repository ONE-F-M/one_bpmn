# Copyright (c) 2026, one-fm and contributors
# WI-001933: a delegation made from inside an agent's TOOL call, to an agent
# that cannot answer immediately.
#
# The failure this covers was silent and total: the tool ran on a synthetic
# task that exists only for the duration of the call, so there was nothing to
# park. The connector's waiting marker came back to the model as though it were
# the answer, the agent said "sent it to maintenance", and the process
# COMPLETED while the other agent was still working. The other agent then
# finished properly — into nothing.
#
# Two behaviours are pinned here:
#   1. execute_shape raises ToolDeferred rather than returning the marker;
#   2. the step loop turns that into a suspension, so the agent stops instead
#      of carrying on with a non-answer.

from __future__ import annotations

import asyncio
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.agents.shape_tools import ToolDeferred, execute_shape
from one_bpmn.one_bpmn.connectors.a2a_client_ops import A2A_WAITING_KEY

MARKER = {"a2a_task": "A2A-TEST-1", "label": "Delegated to Slow Agent", "remote_task_id": None}


# A connector shape as the compiler actually emits one. These tests are about
# deferral rather than wiring, but the descriptor still has to be real: a
# connector with no connectorId resolves no handler, and execute_shape now
# refuses it up front instead of letting it answer with a silent success
# (WI-002960 — an exported map arrived with the wiring missing from its tool
# descriptors, and the agent reported a connector that was never built).
_WIRED = {
	"serviceType": "connector",
	"connectorId": "a2a",
	"operation": "delegate_to_local_agent",
}


class _ParkingInstance:
	"""An instance whose service-task dispatch parks instead of answering —
	what a delegation to an agent waiting on a person actually does."""

	def __init__(self):
		self.name = "INST-DEFER"
		self.context_doctype = ""
		self.context_docname = ""
		self.process_model = ""
		self.initiated_by = "Administrator"
		self._service_task_extensions = {"delegate": _WIRED}

	def _dispatch_service_task(self, task, task_cfg=None):
		task.data[A2A_WAITING_KEY] = dict(MARKER)
		return True


class _AnsweringInstance(_ParkingInstance):
	"""The fast case: the delegate replied inside the call, nothing parks."""

	def _dispatch_service_task(self, task, task_cfg=None):
		task.data["answer"] = "Critical"
		return True


class TestExecuteShapeDeferral(FrappeTestCase):
	def test_parked_dispatch_raises_tool_deferred(self):
		with self.assertRaises(ToolDeferred) as caught:
			execute_shape(_ParkingInstance(), "delegate", _WIRED, {"instruction": "x"})
		self.assertEqual(caught.exception.marker.get("a2a_task"), "A2A-TEST-1")

	def test_the_marker_is_never_returned_as_an_answer(self):
		"""The specific regression: the model must not be handed
		_bpmn_a2a_waiting as if it were a result."""
		try:
			result = execute_shape(
				_ParkingInstance(), "delegate", _WIRED, {"instruction": "x"}
			)
		except ToolDeferred:
			return  # correct — nothing was returned at all
		self.assertNotIn(A2A_WAITING_KEY, result)
		self.fail(f"a parked delegation returned a result instead of deferring: {result}")

	def test_an_immediate_answer_still_returns_normally(self):
		result = execute_shape(
			_AnsweringInstance(), "delegate", _WIRED, {"instruction": "x"}
		)
		self.assertEqual(json.loads(result).get("answer"), "Critical")


class _Step:
	def __init__(self, tool_calls, content=""):
		self.tool_calls = tool_calls
		self.content = content
		self.prompt_tokens = 0
		self.completion_tokens = 0
		self.cache_read_tokens = 0
		self.cache_write_tokens = 0


class _Call:
	def __init__(self, name, arguments):
		self.id = "call_1"
		self.name = name
		self.arguments = arguments


class _Adapter:
	"""Asks for the deferring tool on the first turn, then answers."""

	def __init__(self):
		self.turns = 0

	async def step(self, system, transcript, tools=None, max_tokens=0):
		self.turns += 1
		if self.turns == 1:
			return _Step([_Call("delegate", {"instruction": "fix the flood"})])
		return _Step([], content="all done")


class TestStepLoopSuspendsOnDeferral(FrappeTestCase):
	def test_a_deferred_tool_suspends_the_loop(self):
		def fn(**kwargs):
			raise ToolDeferred(dict(MARKER))

		tool = ToolSpec(fn=fn, name="delegate", description="delegate", parameters={}, required=[])
		result, suspension = asyncio.run(
			run_agent_loop(_Adapter(), system="s", user="u", tools=[tool], max_turns=4)
		)
		self.assertIsNone(result, "the loop must not produce an answer while a delegation is pending")
		self.assertIsNotNone(suspension)
		self.assertEqual(suspension.pending_call.get("name"), "delegate")
		# The marker rides along so the dispatcher knows an AGENT is owed, not a
		# person — that is what stops it spawning a human task.
		self.assertEqual(suspension.deferred_wait.get("a2a_task"), "A2A-TEST-1")

	def test_a_normal_tool_does_not_suspend(self):
		tool = ToolSpec(
			fn=lambda **kw: "Critical",
			name="delegate",
			description="delegate",
			parameters={},
			required=[],
		)
		result, suspension = asyncio.run(
			run_agent_loop(_Adapter(), system="s", user="u", tools=[tool], max_turns=4)
		)
		self.assertIsNone(suspension)
		self.assertEqual(result.text, "all done")


class TestCallerTaskIdIsNotTheStringNone(FrappeTestCase):
	def test_synthetic_task_records_no_caller_step(self):
		"""A tool call has no SpiffWorkflow task, so there is no step id to
		record. Stringifying it wrote the literal "None", which the reconciler
		would later try to resume."""
		from one_bpmn.one_bpmn.connectors.a2a_client_ops import _caller_task_id

		synthetic = frappe._dict(data={}, task_spec=frappe._dict(bpmn_id="delegate"))
		self.assertIsNone(_caller_task_id(synthetic))
		self.assertIsNone(_caller_task_id(None))
		real = frappe._dict(id="3b36f70c-e46c-5ebe-a2d4-3eb69560c9fc")
		self.assertEqual(_caller_task_id(real), "3b36f70c-e46c-5ebe-a2d4-3eb69560c9fc")
