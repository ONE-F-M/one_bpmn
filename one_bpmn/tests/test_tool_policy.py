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

	def test_a_retired_action_label_falls_back_to_deny(self):
		"""Refusing is the only action. Rows written before "Require Human
		Approval" was removed still carry that label, and an unmapped label MUST
		land on DENY — read as "not a deny, therefore allowed" it would turn
		every legacy approval rule into a silent hole.

		Asserted on the compiled label rather than by saving such a row: the
		doctype no longer offers the option, so the row this defends against can
		only reach the evaluator from the database, never from the form.
		"""
		self.assertEqual(tp._ACTION_BY_LABEL.get("require human approval", tp.DENY), tp.DENY)
		self.assertEqual(tp._ACTION_BY_LABEL.get("anything at all", tp.DENY), tp.DENY)


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

	def test_a_retired_approval_rule_refuses_rather_than_suspending(self):
		"""There is no approval path any more. A legacy row must abort the call,
		not park the agent on a human task nobody configured."""
		# Seeded as a stored row would compile, not saved: the form cannot
		# produce this any more.
		frappe.cache.set_value(tp._RULE_CACHE_KEY, [{
			"name": "legacy approval rule", "action": tp.DENY, "category": "",
			"doctypes": {"zz protected alpha"}, "tools": set(), "limits": [],
			"message": "", "exempt_agents": set(),
		}])
		tool = ToolSpec(fn=lambda **kw: "SHOULD NOT RUN", name="get_list", description="d")
		adapter = _FakeAdapter([
			StepResult(content="", tool_calls=[
				StepToolCall(id="c1", name="get_list", arguments={"doctype": "ZZ Protected Alpha"})
			]),
			StepResult(content="understood"),
		])

		completion, suspension = self._run(adapter, [tool])

		self.assertIsNone(suspension, "a policy rule must never suspend the agent")
		self.assertIn("Blocked by policy", completion.trace[0].tool_calls[0].result)

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


class TestParameterCeilings(FrappeTestCase):
	"""The transaction-ceiling half of WI-001645: bounds on the argument VALUES,
	not just on which tool may run or which record types it may touch.

	Everything here goes through the pure evaluator, so no agent, workflow or
	model is involved.
	"""

	def setUp(self):
		from one_bpmn.security import tool_policy

		self.tp = tool_policy
		tool_policy.clear_rule_cache()
		self.addCleanup(tool_policy.clear_rule_cache)

	def _rule(self, limits, tools=None, action="Deny", message=""):
		"""Install one rule directly in the cache — the evaluator reads rules
		through load_rules(), so seeding the cache exercises the real path
		without writing rows the rest of the suite would see."""
		import frappe

		frappe.cache.set_value(
			self.tp._RULE_CACHE_KEY,
			[{
				"name": "TEST-CEILING",
				"action": self.tp._ACTION_BY_LABEL.get(action.lower(), self.tp.DENY),
				"category": "",
				"doctypes": set(),
				"tools": {t.lower() for t in (tools or [])},
				"limits": self.tp._parse_limits(limits, "TEST-CEILING"),
				"message": message,
				"exempt_agents": set(),
			}],
		)

	# ── the grammar ──────────────────────────────────────────────────────────

	def test_limits_parse_into_triples(self):
		parsed = self.tp._parse_limits("amount <= 5000\nquantity < 10", "R")
		self.assertEqual(parsed, [("amount", "<=", 5000.0), ("quantity", "<", 10.0)])

	def test_a_malformed_limit_is_skipped_and_not_silently_enforced_as_nothing(self):
		"""A typo'd rule that reads as a ceiling but enforces nothing is the
		worst outcome available, so it is skipped loudly rather than quietly."""
		parsed = self.tp._parse_limits("amount =< 5000\namount <= 900", "R")
		self.assertEqual(parsed, [("amount", "<=", 900.0)])

	def test_an_expression_is_not_a_limit(self):
		"""The grammar is deliberately tiny — a rule is data a non-engineer edits
		in a form, and anything evaluable there is a way to run code."""
		self.assertEqual(self.tp._parse_limits("__import__('os').system('x') <= 1", "R"), [])

	# ── the decision ─────────────────────────────────────────────────────────

	def test_a_call_within_the_ceiling_is_allowed(self):
		self._rule("amount <= 5000")
		self.assertTrue(self.tp.evaluate("pay_supplier", {"amount": 4999}).allowed)

	def test_a_call_over_the_ceiling_is_refused(self):
		self._rule("amount <= 5000")
		decision = self.tp.evaluate("pay_supplier", {"amount": 5001})
		self.assertFalse(decision.allowed)
		self.assertIn("5001", decision.reason)
		self.assertIn("5000", decision.reason)

	def test_exactly_on_the_ceiling_is_allowed(self):
		self._rule("amount <= 5000")
		self.assertTrue(self.tp.evaluate("pay_supplier", {"amount": 5000}).allowed)

	def test_a_nested_amount_is_found(self):
		"""An amount arrives inside doc, or inside filters — checking only the
		top level would miss most real calls."""
		self._rule("amount <= 5000")
		decision = self.tp.evaluate("create_doc", {"doc": {"amount": 9000}})
		self.assertFalse(decision.allowed)

	def test_a_string_amount_is_still_compared(self):
		self._rule("amount <= 5000")
		self.assertFalse(self.tp.evaluate("pay", {"amount": "9000"}).allowed)

	def test_an_unreadable_amount_is_refused_not_waved_through(self):
		"""An amount nobody can verify is not an amount within the ceiling."""
		self._rule("amount <= 5000")
		decision = self.tp.evaluate("pay", {"amount": "lots"})
		self.assertFalse(decision.allowed)
		self.assertIn("not a number", decision.reason)

	def test_a_boolean_does_not_sneak_through_as_one(self):
		"""True == 1 in Python, so a bool would silently pass a ceiling of 5000."""
		self._rule("amount <= 5000")
		self.assertFalse(self.tp.evaluate("pay", {"amount": True}).allowed)

	def test_an_absent_parameter_means_the_rule_does_not_apply(self):
		self._rule("amount <= 5000")
		self.assertTrue(self.tp.evaluate("pay", {"supplier": "ACME"}).allowed)

	def test_a_floor_works_as_well_as_a_ceiling(self):
		self._rule("quantity >= 1")
		self.assertFalse(self.tp.evaluate("order", {"quantity": 0}).allowed)
		self.assertTrue(self.tp.evaluate("order", {"quantity": 1}).allowed)

	def test_a_rule_scoped_to_other_tools_does_not_fire(self):
		self._rule("amount <= 5000", tools=["pay_supplier"])
		self.assertTrue(self.tp.evaluate("read_report", {"amount": 999999}).allowed)
		self.assertFalse(self.tp.evaluate("pay_supplier", {"amount": 999999}).allowed)

	def test_the_rule_message_replaces_the_generated_reason(self):
		self._rule("amount <= 5000", message="Payments above KD 5,000 need a human.")
		self.assertEqual(
			self.tp.evaluate("pay", {"amount": 6000}).reason,
			"Payments above KD 5,000 need a human.",
		)

	def test_a_breach_always_refuses(self):
		"""Refusing is the only action a ceiling can take."""
		self._rule("amount <= 5000")
		decision = self.tp.evaluate("pay", {"amount": 6000})
		self.assertFalse(decision.allowed)
		self.assertEqual(decision.outcome, self.tp.DENY)

	# ── the interceptor actually stops the call ──────────────────────────────

	def test_the_guard_aborts_the_tool_before_it_runs(self):
		"""The point of the whole control: the tool body must never execute."""
		self._rule("amount <= 5000")
		ran = []

		def pay(**kwargs):
			ran.append(kwargs)
			return "paid"

		guarded = self.tp.guard(pay, "pay")
		with self.assertRaises(self.tp.PolicyViolation):
			guarded(amount=9000)
		self.assertEqual(ran, [], "the tool ran despite breaking the ceiling")

		self.assertEqual(guarded(amount=10), "paid")
		self.assertEqual(len(ran), 1)

	def test_a_decorated_tool_is_still_guarded(self):
		"""guard() used __wrapped__ as its already-guarded marker, which
		functools.wraps sets on ANY decorated function — so a decorated tool
		read as already guarded and was silently left unprotected."""
		import functools

		from one_bpmn.agents.llm_provider.base import ToolSpec

		def raw(**kwargs):
			return "ran"

		@functools.wraps(raw)
		def decorated(**kwargs):
			return raw(**kwargs)

		spec = ToolSpec(fn=decorated, name="pay", description="d")
		self.assertIsNotNone(
			getattr(spec.fn, "__policy_guarded__", None)
			or getattr(getattr(spec.fn, "__pii_wrapped__", None), "__policy_guarded__", None),
			"a decorated tool was not wrapped by the policy interceptor",
		)


class TestTheRuleFormWillSave(FrappeTestCase):
	"""A ceiling nobody can save is not a control. The save-time validation
	predated parameter limits and demanded a Restricted DocType, which made a
	pure transaction ceiling unsavable."""

	def _rule(self, **kwargs):
		values = {
			"doctype": "AI Tool Policy Rule",
			"rule_name": kwargs.pop("rule_name", "ZZ test ceiling"),
			"enabled": 1,
			"action": "Deny",
		}
		values.update(kwargs)
		doc = frappe.get_doc(values)
		self.addCleanup(
			lambda n=values["rule_name"]: frappe.db.exists("AI Tool Policy Rule", n)
			and frappe.delete_doc("AI Tool Policy Rule", n, force=True, ignore_permissions=True)
		)
		return doc

	def test_a_rule_with_only_a_parameter_limit_saves(self):
		doc = self._rule(parameter_limits="amount <= 5000", restricted_tools="pay")
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("AI Tool Policy Rule", doc.name))

	def test_a_rule_with_only_a_doctype_still_saves(self):
		doc = self._rule(rule_name="ZZ test doctype only", restricted_doctypes="Salary Slip")
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("AI Tool Policy Rule", doc.name))

	def test_a_rule_that_matches_nothing_is_still_refused(self):
		doc = self._rule(rule_name="ZZ test empty")
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_an_unreadable_limit_is_refused_at_save_rather_than_skipped(self):
		"""At runtime a bad line is skipped and logged — it must be, or one bad
		character takes the whole policy down. But while a person is here to fix
		it, a silently-skipped ceiling reads as enforced and is not."""
		doc = self._rule(rule_name="ZZ test bad limit", parameter_limits="amount is big")
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_an_expression_is_refused_at_save(self):
		doc = self._rule(
			rule_name="ZZ test expression",
			parameter_limits="__import__('os').system('id') <= 1",
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_blank_lines_and_spacing_do_not_trip_the_check(self):
		doc = self._rule(
			rule_name="ZZ test spacing",
			parameter_limits="\n  amount <= 5000  \n\n quantity >= 1 \n",
			restricted_tools="pay",
		)
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("AI Tool Policy Rule", doc.name))
