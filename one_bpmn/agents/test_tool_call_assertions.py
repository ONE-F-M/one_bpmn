# Copyright (c) 2026, one-fm and contributors
"""Assertions on the tool-call trace: which tools ran, in what order, with what
arguments.

The failure these exist to catch is the fragile success — the answer reads
right, so every text assertion passes, while the trace shows the agent guessed
instead of looking it up, or wrote before it reviewed. Output-only scoring
cannot tell those apart from the real thing.

The evaluator is a pure function of (mode, facts), so the modes and the matchers
are tested directly, without a run. The two tests that need a case go through
the document, because the order rule for anything allowed to act is enforced
there.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_suite
from one_bpmn.agents.eval_runner import _evaluate_tool_calls, _expected_tool_calls

PREFIX = "ZZ ToolCalls"


def facts(trace, expected):
	"""The execution facts an assertion is scored against."""
	return {"tool_trace": trace, "expected_tool_calls": expected}


def call(tool, **args):
	return {"tool": tool, "args": args, "status": "Success"}


def want(order, tool, *matchers):
	return {"order": order, "tool": tool, "matchers": list(matchers)}


def matcher(argument, kind, expected):
	return {"argument": argument, "matcher": kind, "expected": expected}


class TestToolCallModes(FrappeTestCase):
	def test_exact_accepts_the_same_calls_in_the_same_order(self):
		result = _evaluate_tool_calls("EXACT", facts(
			[call("read_api_docs"), call("draft_connector")],
			[want(1, "read_api_docs"), want(2, "draft_connector")],
		))
		self.assertTrue(result["passed"], result["message"])

	def test_exact_rejects_a_swapped_order(self):
		result = _evaluate_tool_calls("EXACT", facts(
			[call("draft_connector"), call("read_api_docs")],
			[want(1, "read_api_docs"), want(2, "draft_connector")],
		))
		self.assertFalse(result["passed"])
		self.assertIn("Call 1", result["message"])

	def test_exact_rejects_an_extra_call(self):
		"""The whole point of EXACT: a review that also wrote is not the same run."""
		result = _evaluate_tool_calls("EXACT", facts(
			[call("read_api_docs"), call("draft_connector"), call("write_connector")],
			[want(1, "read_api_docs"), want(2, "draft_connector")],
		))
		self.assertFalse(result["passed"])
		self.assertIn("the run made 3", result["message"])

	def test_in_order_allows_calls_in_between(self):
		result = _evaluate_tool_calls("IN_ORDER", facts(
			[call("read_api_docs"), call("wi_comment"), call("draft_connector")],
			[want(1, "read_api_docs"), want(2, "draft_connector")],
		))
		self.assertTrue(result["passed"], result["message"])

	def test_in_order_rejects_the_reverse_sequence(self):
		"""Reviewing after writing passes ANY_ORDER and must not pass IN_ORDER."""
		result = _evaluate_tool_calls("IN_ORDER", facts(
			[call("write_connector"), call("review_connector")],
			[want(1, "review_connector"), want(2, "write_connector")],
		))
		self.assertFalse(result["passed"])
		self.assertIn("write_connector", result["message"])

	def test_any_order_ignores_sequence(self):
		result = _evaluate_tool_calls("ANY_ORDER", facts(
			[call("write_connector"), call("review_connector")],
			[want(1, "review_connector"), want(2, "write_connector")],
		))
		self.assertTrue(result["passed"], result["message"])

	def test_any_order_still_requires_every_expected_call(self):
		result = _evaluate_tool_calls("ANY_ORDER", facts(
			[call("review_connector")],
			[want(1, "review_connector"), want(2, "write_connector")],
		))
		self.assertFalse(result["passed"])
		self.assertIn("Never called: write_connector", result["message"])

	def test_the_same_tool_twice_needs_two_actual_calls(self):
		"""Two expected calls to one tool must not both match the same actual call."""
		result = _evaluate_tool_calls("ANY_ORDER", facts(
			[call("test_operation")],
			[want(1, "test_operation"), want(2, "test_operation")],
		))
		self.assertFalse(result["passed"])

	def test_an_empty_trace_fails_rather_than_passing_vacuously(self):
		result = _evaluate_tool_calls("IN_ORDER", facts([], [want(1, "read_api_docs")]))
		self.assertFalse(result["passed"])
		self.assertIn("nothing", result["message"])

	def test_a_replay_says_it_cannot_see_tool_calls(self):
		result = _evaluate_tool_calls("EXACT", None)
		self.assertTrue(result["error"])

	def test_an_unknown_mode_is_an_error_not_a_failure(self):
		result = _evaluate_tool_calls("SOMEHOW", facts([call("x")], [want(1, "x")]))
		self.assertTrue(result["error"])
		self.assertIn("EXACT", result["message"])

	def test_a_case_with_no_expected_calls_is_an_error(self):
		result = _evaluate_tool_calls("EXACT", facts([call("x")], []))
		self.assertTrue(result["error"])


class TestArgumentMatchers(FrappeTestCase):
	def test_equals_compares_the_whole_value(self):
		expected = [want(1, "read_api_docs", matcher("url", "equals", "https://api.frankfurter.dev"))]
		self.assertTrue(_evaluate_tool_calls("EXACT", facts(
			[call("read_api_docs", url="https://api.frankfurter.dev")], expected))["passed"])
		self.assertFalse(_evaluate_tool_calls("EXACT", facts(
			[call("read_api_docs", url="https://api.frankfurter.dev/v1/latest")], expected))["passed"])

	def test_contains_is_a_case_insensitive_substring(self):
		expected = [want(1, "delegate_dev_agent", matcher("instruction", "contains", "staging"))]
		self.assertTrue(_evaluate_tool_calls("EXACT", facts(
			[call("delegate_dev_agent", instruction="Start from branch STAGING and fix the test.")],
			expected))["passed"])

	def test_regex_matches_a_pattern(self):
		expected = [want(1, "get_pull_request", matcher("pr_url", "regex", r"/pull/\d+$"))]
		self.assertTrue(_evaluate_tool_calls("EXACT", facts(
			[call("get_pull_request", pr_url="https://github.com/ONE-F-M/one_bpmn/pull/724")],
			expected))["passed"])
		self.assertFalse(_evaluate_tool_calls("EXACT", facts(
			[call("get_pull_request", pr_url="https://github.com/ONE-F-M/one_bpmn/pulls")],
			expected))["passed"])

	def test_every_matcher_on_a_call_must_hold(self):
		expected = [want(
			1, "wi_set_state",
			matcher("state", "equals", "In Progress"),
			matcher("reason", "contains", "delegated"),
		)]
		self.assertFalse(_evaluate_tool_calls("EXACT", facts(
			[call("wi_set_state", state="In Progress", reason="picked it up myself")], expected))["passed"])

	def test_a_missing_argument_fails_rather_than_passing(self):
		result = _evaluate_tool_calls("EXACT", facts(
			[call("read_api_docs")],
			[want(1, "read_api_docs", matcher("url", "equals", "https://api.frankfurter.dev"))],
		))
		self.assertFalse(result["passed"])
		self.assertIn("no argument", result["message"])

	def test_a_non_string_argument_is_matched_on_its_json(self):
		expected = [want(1, "write_connector", matcher("draft", "contains", "frankfurter"))]
		self.assertTrue(_evaluate_tool_calls("EXACT", facts(
			[call("write_connector", draft={"connectorId": "frankfurter", "operations": []})],
			expected))["passed"])

	def test_matchers_group_by_call_number_not_row_order(self):
		"""The grid is a spreadsheet: re-sorting rows must not change the case."""
		case = frappe._dict(expected_tool_calls=[
			frappe._dict(call_order=2, tool_name="draft_connector", argument="", matcher="equals", expected_value=""),
			frappe._dict(call_order=1, tool_name="read_api_docs", argument="url", matcher="contains", expected_value="frankfurter"),
			frappe._dict(call_order=1, tool_name="read_api_docs", argument="", matcher="equals", expected_value=""),
		])
		grouped = _expected_tool_calls(case)
		self.assertEqual([g["tool"] for g in grouped], ["read_api_docs", "draft_connector"])
		self.assertEqual(len(grouped[0]["matchers"]), 1)


class TestOrderRequiredForActionTier(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# A skill cannot be saved straight into Action-Allowed — graduating to
		# that tier requires eval cases already targeting it, which is the rule
		# this suite exists to serve rather than to test. Set the tier under it.
		self.skill = frappe.get_doc({
			"doctype": "AI Skill",
			"skill_name": f"{PREFIX} write things {frappe.generate_hash(length=5)}",
			"tier": "Draft-Only",
			"description": "Use this skill when something has to be written. Do NOT use it to read.",
			"body": "Writes things.",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("AI Skill", self.skill.name, "tier", "Action-Allowed")
		self.suite = make_eval_suite(title=f"{PREFIX} suite {frappe.generate_hash(length=5)}")

	def _case(self, mode: str, target_skill: str = None):
		case = frappe.get_doc({
			"doctype": "AI Eval Case",
			"suite": self.suite.name,
			"title": f"{PREFIX} case {frappe.generate_hash(length=5)}",
			"input_user_prompt": "do the thing",
			"target_skill": target_skill,
			"assertions": [{"assertion_type": "tool_calls", "value": mode}],
			"expected_tool_calls": [{"call_order": 1, "tool_name": "write_thing"}],
		})
		case.flags.ignore_mandatory = True
		case.flags.ignore_links = True
		return case

	def test_any_order_is_refused_for_an_action_allowed_skill(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._case("ANY_ORDER", self.skill.name).insert(ignore_permissions=True)
		self.assertIn("in order", str(ctx.exception))

	def test_in_order_is_accepted_for_an_action_allowed_skill(self):
		case = self._case("IN_ORDER", self.skill.name)
		case.insert(ignore_permissions=True)
		self.assertTrue(case.name)

	def test_any_order_is_fine_when_nothing_acts(self):
		case = self._case("ANY_ORDER")
		case.insert(ignore_permissions=True)
		self.assertTrue(case.name)

	def test_a_tool_calls_assertion_needs_expected_calls(self):
		case = self._case("EXACT")
		case.expected_tool_calls = []
		with self.assertRaises(frappe.ValidationError) as ctx:
			case.insert(ignore_permissions=True)
		self.assertIn("Expected Tool Calls", str(ctx.exception))

	def test_an_argument_with_no_value_to_match_is_refused(self):
		case = self._case("EXACT")
		case.expected_tool_calls[0].argument = "url"
		case.expected_tool_calls[0].expected_value = ""
		with self.assertRaises(frappe.ValidationError) as ctx:
			case.insert(ignore_permissions=True)
		self.assertIn("no value to match", str(ctx.exception))
