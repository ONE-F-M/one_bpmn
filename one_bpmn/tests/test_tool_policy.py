# Copyright (c) 2026, one-fm and contributors
# Deterministic tool-call interception (WI-001645).
#
# The control's whole value is that it stops a tool BEFORE it runs, from rules
# that are data rather than prompt text. These tests pin the three properties
# that make that true:
#   1. the decision is correct for the seeded rule groups
#   2. the guard is applied at ToolSpec construction, so a tool built anywhere
#      — including inside a Server Script — is covered
#   3. a denial reaches the model as an ordinary tool result, and a
#      require-human decision reuses the existing suspension path

from __future__ import annotations

import asyncio

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall, ToolSpec
from one_bpmn.security import tool_policy as tp

RULE = "ZZ Test Policy Rule"


def _make_rule(**overrides):
	frappe.delete_doc("AI Tool Policy Rule", RULE, force=True, ignore_permissions=True)
	doc = frappe.get_doc({
		"doctype": "AI Tool Policy Rule",
		"rule_name": RULE,
		"enabled": 1,
		"category": "Other",
		"action": "Deny",
		# Deliberately fictional names: the site carries real seeded rules
		# (Role, Server Script, Salary Slip...) and a test that reused one of
		# those would pass or fail for the wrong reason.
		"restricted_doctypes": "ZZ Protected Alpha\nZZ Protected Beta",
		"restricted_tools": "",
		"violation_message": "test rule fired.",
		**overrides,
	})
	doc.insert(ignore_permissions=True)
	tp.clear_rule_cache()
	return doc


class TestPolicyEvaluation(FrappeTestCase):
	def setUp(self):
		_make_rule()
		self.addCleanup(tp.clear_rule_cache)

	def test_restricted_doctype_in_a_plain_argument_is_denied(self):
		self.assertEqual(tp.evaluate("get_list", {"doctype": "ZZ Protected Alpha"}).outcome, tp.DENY)

	def test_restricted_doctype_nested_inside_filters_is_denied(self):
		"""A protected name can arrive buried in a filters dict, not just as a
		top-level `doctype` — matching only on key names would miss it."""
		decision = tp.evaluate("query_documents", {"filters": {"parent": "ZZ Protected Beta"}})
		self.assertEqual(decision.outcome, tp.DENY)

	def test_unrelated_doctype_is_allowed(self):
		self.assertTrue(tp.evaluate("get_list", {"doctype": "Employee"}).allowed)

	def test_matching_is_whole_value_not_substring(self):
		"""'ZZ Protected Alpha Log' contains 'ZZ Protected Alpha'. A substring test would refuse
		harmless calls and would still be trivially defeated by padding."""
		self.assertTrue(tp.evaluate("get_list", {"doctype": "ZZ Protected Alpha Log"}).allowed)

	def test_rule_scoped_to_named_tools_ignores_others(self):
		_make_rule(restricted_tools="transition_workflow")
		self.assertEqual(
			tp.evaluate("transition_workflow", {"doctype": "ZZ Protected Alpha"}).outcome, tp.DENY
		)
		self.assertTrue(tp.evaluate("get_list", {"doctype": "ZZ Protected Alpha"}).allowed)

	def test_disabled_rule_is_not_evaluated(self):
		_make_rule(enabled=0)
		self.assertTrue(tp.evaluate("get_list", {"doctype": "ZZ Protected Alpha"}).allowed)

	def test_require_human_label_is_normalised(self):
		"""The doctype stores 'Require Human Approval'; the loop compares
		against the internal constant. If these ever diverge the suspension
		branch silently never fires."""
		_make_rule(action="Require Human Approval")
		self.assertEqual(
			tp.evaluate("get_list", {"doctype": "ZZ Protected Alpha"}).outcome, tp.REQUIRE_HUMAN
		)


class TestAgentScoping(FrappeTestCase):
	def setUp(self):
		_make_rule()
		self.addCleanup(tp.clear_rule_cache)

	def test_exempt_agent_bypasses_the_rule(self):
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_agent"}, "name")
		if not agent:
			self.skipTest("no logix agent on this site")
		doc = frappe.get_doc("AI Tool Policy Rule", RULE)
		doc.append("exempt_agents", {"agent_configuration": agent, "reason": "test"})
		doc.save(ignore_permissions=True)
		tp.clear_rule_cache()

		self.assertTrue(tp.evaluate("write_script", {"doctype": "ZZ Protected Alpha"},
		                            agent_config=agent).allowed)
		self.assertEqual(
			tp.evaluate("write_script", {"doctype": "ZZ Protected Alpha"}).outcome, tp.DENY
		)

	def test_current_agent_contextvar_is_used_when_not_passed(self):
		"""Tools built inside a Server Script never see the dispatcher's frame,
		so the agent has to travel out-of-band."""
		token = tp.set_current_agent("zz-nonexistent-agent")
		try:
			self.assertEqual(tp.current_agent(), "zz-nonexistent-agent")
		finally:
			tp.reset_current_agent(token)
		self.assertIsNone(tp.current_agent())


class TestGuardAppliedAtConstruction(FrappeTestCase):
	"""The interception point is ToolSpec.__post_init__ — NOT a loop. This is
	what makes a tool built inside a Server Script (as the Logix clarifier does)
	just as guarded as one built by compile_shape_tools."""

	def setUp(self):
		_make_rule()
		self.addCleanup(tp.clear_rule_cache)

	def test_an_arbitrarily_constructed_toolspec_is_guarded(self):
		ran = []
		spec = ToolSpec(fn=lambda **kw: ran.append(kw) or "ok", name="probe", description="p")

		with self.assertRaises(tp.PolicyViolation):
			spec.fn(doctype="ZZ Protected Alpha")
		self.assertEqual(ran, [], "the tool body must not run when denied")

		self.assertEqual(spec.fn(doctype="Employee"), "ok")

	def test_human_tools_are_not_wrapped(self):
		"""A human tool's fn is a stub that must never run; wrapping it would
		put a policy check in front of something that is already unreachable."""
		spec = ToolSpec(fn=lambda **kw: "x", name="approve", description="d", human=True)
		self.assertIsNone(getattr(spec.fn, "__wrapped__", None))

	def test_guard_is_not_applied_twice(self):
		inner = ToolSpec(fn=lambda **kw: "ok", name="probe", description="p")
		again = ToolSpec(fn=inner.fn, name="probe", description="p")
		self.assertIs(again.fn, inner.fn)


class _FakeAdapter:
	def __init__(self, steps):
		self.steps = list(steps)

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		return self.steps.pop(0)


class TestLoopIntegration(FrappeTestCase):
	def setUp(self):
		_make_rule()
		self.addCleanup(tp.clear_rule_cache)

	def _run(self, adapter, tools):
		return asyncio.run(
			run_agent_loop(adapter, system="s", user="u", tools=tools,
			               max_tokens=100, max_turns=5)
		)

	def test_denied_call_returns_a_tool_result_the_model_can_act_on(self):
		"""A denial is handled exactly like any other tool failure — the loop
		keeps going and the model gets told why."""
		tool = ToolSpec(fn=lambda **kw: "SHOULD NOT RUN", name="get_list", description="d",
		                parameters={"doctype": {"type": "string"}})
		adapter = _FakeAdapter([
			StepResult(content="", tool_calls=[
				StepToolCall(id="c1", name="get_list", arguments={"doctype": "ZZ Protected Alpha"})
			]),
			StepResult(content="understood"),
		])

		completion, suspension = self._run(adapter, [tool])

		self.assertIsNone(suspension)
		self.assertEqual(completion.text, "understood")
		result = completion.trace[0].tool_calls[0].result
		self.assertIn("Blocked by policy", result)
		self.assertNotIn("SHOULD NOT RUN", result)

	def test_require_human_suspends_instead_of_denying(self):
		"""Reuses the durable-HITL suspension path rather than a second
		mechanism — the call becomes the turn's pending human decision."""
		_make_rule(action="Require Human Approval")
		tool = ToolSpec(fn=lambda **kw: "SHOULD NOT RUN", name="get_list", description="d")
		adapter = _FakeAdapter([
			StepResult(content="", tool_calls=[
				StepToolCall(id="c1", name="get_list", arguments={"doctype": "ZZ Protected Alpha"})
			]),
		])

		completion, suspension = self._run(adapter, [tool])

		self.assertIsNone(completion)
		self.assertIsNotNone(suspension)
		self.assertEqual(suspension.pending_call["name"], "get_list")

	def test_allowed_call_is_completely_unaffected(self):
		"""The regression guard: anything the policy does not match must behave
		exactly as it did before this story."""
		tool = ToolSpec(fn=lambda **kw: "42", name="get_list", description="d")
		adapter = _FakeAdapter([
			StepResult(content="", tool_calls=[
				StepToolCall(id="c1", name="get_list", arguments={"doctype": "Employee"})
			]),
			StepResult(content="done"),
		])

		completion, _ = self._run(adapter, [tool])

		self.assertEqual(completion.trace[0].tool_calls[0].result, "42")


class TestObservability(FrappeTestCase):
	def test_denied_result_is_classified_as_denied_not_error(self):
		from one_bpmn.agents.observability import _tool_call_status

		self.assertEqual(_tool_call_status("Blocked by policy: nope"), "Denied")
		self.assertEqual(_tool_call_status("Error calling x: boom"), "Error")
		self.assertEqual(_tool_call_status("Unknown tool: x"), "Error")
		self.assertEqual(_tool_call_status("42"), "Success")
