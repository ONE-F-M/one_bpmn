# Copyright (c) 2026, one-fm and contributors
"""One pause per turn means one delegation per turn — enforced before work starts.
The step loop can track exactly one pause per turn: the first ToolDeferred takes
the slot. Nothing used to stop a model from calling several delegation tools in a
single assistant turn, and ``local.delegate()`` creates the A2A Task and starts
the agent BEFORE anything parks. So the extra delegations were abandoned
mid-flight: live, unwatched, and non-terminal until their deadline expired. The
model was then told to call them again, so each one also ran twice.
Observed with four specialists on one brief: three delegations in one turn
produced five A2A Tasks — one tracked, two orphaned in "working" forever, and two
duplicates from the retry.
The guard therefore sits in the connector, before the row exists, keyed off a
request-scoped flag the loop owns. These tests pin both halves and the leak that
the first attempt at the fix introduced.
"""

from __future__ import annotations

import asyncio

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import (
	_SECOND_HUMAN_RESULT,
	_SECOND_PAUSE_RESULT,
	run_agent_loop,
)
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.agents.shape_tools import PAUSE_HELD_FLAG, ToolDeferred
from one_bpmn.one_bpmn.connectors import a2a_client_ops


class _Call:
	def __init__(self, idx, name):
		self.id = f"c{idx}"
		self.name = name
		self.arguments = {"instruction": "go"}


class _Step:
	def __init__(self, calls, content=""):
		self.tool_calls = calls
		self.content = content
		self.prompt_tokens = 1
		self.completion_tokens = 1
		self.cache_read_tokens = 0
		self.cache_write_tokens = 0


class _Adapter:
	"""Replays canned steps and records the flag as each turn begins."""

	def __init__(self, steps):
		self.steps = list(steps)
		self.flag_at_turn_start = []

	async def step(self, system, transcript, tools=None, max_tokens=0):
		self.flag_at_turn_start.append(frappe.flags.get(PAUSE_HELD_FLAG))
		return self.steps.pop(0)


def _run(adapter, tools, max_turns=4):
	return asyncio.run(
		run_agent_loop(adapter, system="s", user="u", tools=tools, max_turns=max_turns)
	)


class TestOneDelegationPerTurn(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.started = []
		frappe.flags[PAUSE_HELD_FLAG] = False

	def tearDown(self):
		frappe.flags[PAUSE_HELD_FLAG] = False
		super().tearDown()

	def _delegating_tool(self, name):
		"""Stands in for a delegation shape, including the connector's guard:
		refuse before starting anything when a pause is already held."""

		def fn(**kwargs):
			if frappe.flags.get(PAUSE_HELD_FLAG):
				return '{"state": "not-started", "reason": "another-delegation-pending"}'
			self.started.append(name)
			raise ToolDeferred({"a2a_task": f"TASK-{name}"})

		return ToolSpec(fn=fn, name=name, description="d", parameters={}, required=[])

	def test_only_one_delegation_starts_per_turn(self):
		"""Three delegation calls in one turn must start exactly one."""
		names = ["deleg_a", "deleg_b", "deleg_c"]
		tools = [self._delegating_tool(n) for n in names]
		_, suspension = _run(_Adapter([_Step([_Call(i, n) for i, n in enumerate(names)])]), tools)

		self.assertEqual(self.started, ["deleg_a"], "more than one delegation was started")
		self.assertIsNotNone(suspension)
		self.assertEqual(suspension.pending_call.get("name"), "deleg_a")

	def test_the_calls_that_did_not_start_still_get_a_result(self):
		"""Wire formats need a result for every call, and the model needs to know
		it must come back to them."""
		names = ["deleg_a", "deleg_b", "deleg_c"]
		tools = [self._delegating_tool(n) for n in names]
		_, suspension = _run(_Adapter([_Step([_Call(i, n) for i, n in enumerate(names)])]), tools)

		others = [r for r in suspension.deferred_results if r["name"] != "deleg_a"]
		self.assertEqual(len(others), 2)
		for row in others:
			self.assertIn("not-started", row["content"])

	def test_flag_is_clear_when_each_turn_begins(self):
		"""Set deliberately dirty: a turn must never inherit a held pause."""
		frappe.flags[PAUSE_HELD_FLAG] = True
		tools = [self._delegating_tool("deleg_a")]
		adapter = _Adapter([_Step([_Call(0, "deleg_a")])])
		_run(adapter, tools)
		self.assertEqual(adapter.flag_at_turn_start, [False])

	def test_flag_does_not_leak_past_a_final_answer(self):
		"""The regression the first cut of this fix introduced. A turn that held a
		pause, followed by a turn that answers, must leave the flag clear — or a
		later delegating step in the SAME request is wrongly refused."""
		tools = [self._delegating_tool("deleg_a")]
		adapter = _Adapter([
			_Step([_Call(0, "deleg_a")]),   # holds the pause
			_Step([], content="done"),      # answers
		])
		# Resume straight past the suspension into the answering turn.
		_run(adapter, tools)
		frappe.flags[PAUSE_HELD_FLAG] = True
		_, _ = _run(_Adapter([_Step([], content="done")]), tools)
		self.assertFalse(
			frappe.flags.get(PAUSE_HELD_FLAG),
			"flag survived the loop and would refuse an unrelated later delegation",
		)

	def test_the_flag_does_not_survive_a_suspension(self):
		"""The leak that actually bit, in production rather than in a test.

		frappe.flags lives for the whole worker job. The loop also exits by
		SUSPENDING, and clearing only at the top of a turn left the flag True on
		that path — so the next delegation handled by the same worker was
		refused as though a pause were still open. Observed live: an
		orchestrator's delegation returned "not-started", created no A2A Task,
		and the agent correctly reported that the specialist confirmed nothing.
		"""
		tools = [self._delegating_tool("deleg_a")]
		_, suspension = _run(_Adapter([_Step([_Call(0, "deleg_a")])]), tools)
		self.assertIsNotNone(suspension, "this test needs the loop to suspend")
		self.assertFalse(
			frappe.flags.get(PAUSE_HELD_FLAG),
			"the pause flag survived a suspension and would refuse the next "
			"delegation this worker handles",
		)

	def test_a_second_pause_is_not_blamed_on_a_human_task(self):
		"""If a tool gets past the connector guard and parks anyway, the model is
		told the truth. It used to be told a human task was pending."""

		def parks_regardless(**kwargs):
			raise ToolDeferred({"a2a_task": "TASK-x"})

		tools = [
			self._delegating_tool("deleg_a"),
			ToolSpec(fn=parks_regardless, name="deleg_b", description="d", parameters={}, required=[]),
		]
		_, suspension = _run(
			_Adapter([_Step([_Call(0, "deleg_a"), _Call(1, "deleg_b")])]), tools
		)
		second = [r for r in suspension.deferred_results if r["name"] == "deleg_b"][0]
		self.assertIn(_SECOND_PAUSE_RESULT, second["content"])
		self.assertNotIn(_SECOND_HUMAN_RESULT, second["content"])

	def test_a_second_human_tool_still_says_human(self):
		"""The human message keeps its own wording — this fix must not blur them."""
		human = lambda **kw: "unused"  # noqa: E731 — never called; selecting it suspends
		tools = [
			ToolSpec(fn=human, name="ask_a", description="d", parameters={}, required=[], human=True),
			ToolSpec(fn=human, name="ask_b", description="d", parameters={}, required=[], human=True),
		]
		_, suspension = _run(_Adapter([_Step([_Call(0, "ask_a"), _Call(1, "ask_b")])]), tools)
		second = [r for r in suspension.deferred_results if r["name"] == "ask_b"][0]
		self.assertIn(_SECOND_HUMAN_RESULT, second["content"])


class TestConnectorGuard(FrappeTestCase):
	"""The load-bearing half: nothing is created while a pause is held."""

	class _FakeTask:
		"""Enough of an A2A Task for the parking path: still working, so the op
		takes its normal branch and we can see that it got that far."""

		name = "A2A-TEST"
		state = "working"
		agent_configuration = "Some Agent"

		def db_set(self, *args, **kwargs):
			pass

	def setUp(self):
		super().setUp()
		self.calls = []
		self._orig = a2a_client_ops.local.delegate

		def _fake_delegate(*args, **kwargs):
			self.calls.append((args, kwargs))
			return self._FakeTask()

		a2a_client_ops.local.delegate = _fake_delegate

	def tearDown(self):
		a2a_client_ops.local.delegate = self._orig
		frappe.flags[PAUSE_HELD_FLAG] = False
		super().tearDown()

	def test_refuses_without_creating_an_a2a_task(self):
		frappe.flags[PAUSE_HELD_FLAG] = True
		out = a2a_client_ops.delegate_to_local_agent(
			{"agent": "Some Agent", "instruction": "go"}, {}
		)
		self.assertEqual(out.get("state"), "not-started")
		self.assertEqual(out.get("reason"), "another-delegation-pending")
		self.assertIn("Some Agent", out.get("text") or "")
		self.assertEqual(self.calls, [], "a delegation was started that nothing could track")

	def test_delegates_normally_when_no_pause_is_held(self):
		frappe.flags[PAUSE_HELD_FLAG] = False
		a2a_client_ops.delegate_to_local_agent({"agent": "Some Agent", "instruction": "go"}, {})
		self.assertEqual(len(self.calls), 1, "the guard blocked a delegation it should have allowed")

	def test_a_missing_instruction_still_fails_before_the_guard(self):
		"""Argument validation keeps precedence — the guard is not a way to make a
		malformed call look merely postponed."""
		frappe.flags[PAUSE_HELD_FLAG] = True
		with self.assertRaises(Exception):
			a2a_client_ops.delegate_to_local_agent({"agent": "Some Agent", "instruction": " "}, {})
		self.assertEqual(self.calls, [])
