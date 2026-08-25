# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A connector tool that is not wired up must say so, not answer "ok".

An Orchestrator Agent map was exported from one site and imported into two
others. The diagram was perfect. The compiled spec that travelled with it had
been built by an older compiler which did not copy ``connectorId``,
``operation`` and ``resultVariable`` onto the agent's TOOL descriptors — only
onto the shape's own dispatch config.

So the delegate tool no longer knew which connector to call. The dispatcher
resolved no handler and returned without doing anything; nothing was written to
task.data; and ``execute_shape``'s empty-result fallback answered ``{"ok":
true}``. The orchestrator read that as success and reported a connector built by
a specialist that was never asked — the whole run took forty-five seconds, where
a real connector build takes minutes.

Two defences, tested here:

- the wiring is taken from the shape's own descriptor when the tool entry lacks
  it, so a map that is merely compiled-behind keeps working; and
- when it genuinely cannot be resolved, the tool returns an error that tells the
  model not to retry and not to claim the work is done — because the thing that
  made this expensive was not the breakage, it was the confident report.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import (
	_missing_dispatch_wiring,
	_with_dispatch_wiring,
	execute_shape,
)


class _Instance:
	"""Enough of a process instance for the wiring lookup and dispatch."""

	def __init__(self, service_task_extensions=None, on_dispatch=None):
		self._service_task_extensions = service_task_extensions or {}
		self.context_doctype = ""
		self.context_docname = ""
		self.dispatched = []
		self._on_dispatch = on_dispatch

	def _dispatch_service_task(self, task, task_cfg):
		self.dispatched.append(dict(task_cfg))
		if self._on_dispatch:
			self._on_dispatch(task, task_cfg)


TOOL_ENTRY = {"serviceType": "connector"}
SHAPE_CFG = {
	"serviceType": "connector",
	"connectorId": "a2a",
	"operation": "delegate_to_local_agent",
	"resultVariable": "connector_result",
	"connectorParams": '{"agent":"Connector Agent"}',
}


class TestTheToolCarriesItsWiring(FrappeTestCase):
	# ── the merge ────────────────────────────────────────────────────────

	def test_wiring_is_taken_from_the_shape_when_the_tool_entry_lacks_it(self):
		inst = _Instance({"delegate": SHAPE_CFG})
		merged = _with_dispatch_wiring(inst, "delegate", dict(TOOL_ENTRY))
		self.assertEqual(merged["connectorId"], "a2a")
		self.assertEqual(merged["operation"], "delegate_to_local_agent")
		self.assertEqual(merged["resultVariable"], "connector_result")

	def test_the_tool_entry_wins_where_it_says_something(self):
		"""It is the more specific of the two — a shape used as a tool may
		deliberately differ from the shape as the process runs it."""
		inst = _Instance({"delegate": SHAPE_CFG})
		merged = _with_dispatch_wiring(
			inst, "delegate", {**TOOL_ENTRY, "operation": "something_else"}
		)
		self.assertEqual(merged["operation"], "something_else")
		self.assertEqual(merged["connectorId"], "a2a")

	def test_a_complete_tool_entry_is_left_alone(self):
		inst = _Instance({"delegate": {"connectorId": "wrong", "operation": "wrong"}})
		full = {**TOOL_ENTRY, "connectorId": "a2a", "operation": "delegate_to_local_agent"}
		self.assertEqual(_with_dispatch_wiring(inst, "delegate", full), full)

	def test_a_non_connector_shape_is_not_touched(self):
		"""An ai_agent or script shape carries its own config and fails visibly;
		only the connector case returns in silence."""
		inst = _Instance({"x": SHAPE_CFG})
		cfg = {"serviceType": "ai_agent", "aiSystemPrompt": "hi"}
		self.assertEqual(_with_dispatch_wiring(inst, "x", cfg), cfg)
		self.assertEqual(_missing_dispatch_wiring(cfg), [])

	def test_nothing_to_merge_from_is_survivable(self):
		inst = _Instance({})
		self.assertEqual(_with_dispatch_wiring(inst, "delegate", dict(TOOL_ENTRY)), TOOL_ENTRY)

	# ── what is still missing ────────────────────────────────────────────

	def test_missing_wiring_is_named(self):
		self.assertEqual(
			sorted(_missing_dispatch_wiring({"serviceType": "connector"})),
			["connectorId", "operation"],
		)

	def test_a_blank_string_counts_as_missing(self):
		"""The compiled spec carries "" rather than absent, and "" resolves no
		handler just as surely as None."""
		self.assertEqual(
			_missing_dispatch_wiring(
				{"serviceType": "connector", "connectorId": "  ", "operation": ""}
			),
			["connectorId", "operation"],
		)

	# ── the behaviour that actually cost a day ───────────────────────────

	def test_an_unwired_connector_tool_reports_an_error_not_ok(self):
		"""The regression itself. It must not come back as success."""
		inst = _Instance({})
		out = json.loads(execute_shape(inst, "delegate", dict(TOOL_ENTRY), {"instruction": "x"}))
		self.assertIn("error", out)
		self.assertNotIn("ok", out)
		self.assertEqual(inst.dispatched, [], "nothing should have been dispatched")

	def test_the_error_tells_the_model_not_to_retry_or_claim_success(self):
		"""What made this expensive was not the breakage but the confident
		report that followed it."""
		inst = _Instance({})
		out = json.loads(execute_shape(inst, "delegate", dict(TOOL_ENTRY), {"instruction": "x"}))
		self.assertFalse(out.get("retryable"))
		lowered = out["error"].lower()
		self.assertIn("nothing ran", lowered)
		self.assertIn("do not report the work as done", lowered)
		self.assertIn("delegate", lowered, "the message should name the tool")

	def test_a_stale_spec_still_dispatches_once_the_wiring_is_recovered(self):
		"""The common case: the map is right, its compiled copy is behind."""
		inst = _Instance({"delegate": SHAPE_CFG})
		execute_shape(inst, "delegate", dict(TOOL_ENTRY), {"instruction": "x"})
		self.assertEqual(len(inst.dispatched), 1)
		self.assertEqual(inst.dispatched[0]["connectorId"], "a2a")

	def test_a_dispatch_that_produces_nothing_still_reads_as_ok(self):
		"""Deliberately unchanged. A wired tool that legitimately returns no
		variables is not an error, and turning that into one would break every
		fire-and-forget shape."""
		inst = _Instance({"delegate": SHAPE_CFG})
		out = json.loads(execute_shape(inst, "delegate", dict(TOOL_ENTRY), {"instruction": "x"}))
		self.assertTrue(out.get("ok"))
