# Copyright (c) 2026, one-fm and contributors
# WI-001364 (5-04): backend=replay — re-evaluate assertions against stored
# outputs without new LLM calls.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import eval_runner

test_ignore = ["AI Eval Suite", "AI Eval Case"]


def _eval_events(publish):
	return [c for c in publish.call_args_list if c.args and c.args[0] == "eval_run_completed"]


def _fixture(with_prior_output=None, assertion=None):
	suite = frappe.get_doc(
		{"doctype": "AI Eval Suite", "title": f"Replay Suite {frappe.generate_hash(length=5)}"}
	)
	suite.flags.ignore_mandatory = True
	suite.insert(ignore_permissions=True, ignore_mandatory=True)

	case = frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"title": "replay-case",
			"suite": suite.name,
			"backend": "direct_api",
			"input_user_prompt": "say hello world",
		}
	)
	if assertion:
		case.append("assertions", assertion)
	case.flags.ignore_mandatory = True
	case.insert(ignore_permissions=True, ignore_mandatory=True)

	if with_prior_output is not None:
		prior = frappe.new_doc("AI Eval Run")
		prior.suite = suite.name
		prior.status = "Passed"
		prior.backend = "live"
		prior.started_at = frappe.utils.now_datetime()
		prior.append(
			"results",
			{"eval_case": case.name, "status": "Passed", "actual_output": with_prior_output},
		)
		prior.flags.ignore_mandatory = True
		prior.insert(ignore_permissions=True, ignore_mandatory=True)

	return suite, case


def _replay(suite):
	run = frappe.new_doc("AI Eval Run")
	run.suite = suite.name
	run.status = "Running"
	run.backend = "replay"
	run.started_at = frappe.utils.now_datetime()
	run.flags.ignore_mandatory = True
	run.insert(ignore_permissions=True, ignore_mandatory=True)
	with patch.object(frappe, "publish_realtime") as publish:
		eval_runner._execute_eval_suite(run.name)
	return frappe.get_doc("AI Eval Run", run.name), publish


class TestEvalReplay(FrappeTestCase):
	# ── Scenario 1: prior result replayed, no executor call ──

	def test_replay_uses_stored_output_without_executor(self):
		suite, _ = _fixture(
			with_prior_output="hello world",
			assertion={"assertion_type": "contains", "value": "hello"},
		)
		with patch.object(eval_runner, "get_executor") as executor:
			run, _ = _replay(suite)
		executor.assert_not_called()
		self.assertEqual(run.status, "Passed")
		self.assertEqual(run.results[0].actual_output, "hello world")

	def test_replay_reflects_changed_assertion(self):
		# The point of replay: an assertion change re-validates old output free.
		suite, _ = _fixture(
			with_prior_output="hello world",
			assertion={"assertion_type": "contains", "value": "goodbye"},
		)
		run, _ = _replay(suite)
		self.assertEqual(run.status, "Failed")

	# ── Scenario 2: no prior result → explicit Error ──

	def test_replay_without_prior_result_is_error(self):
		suite, _ = _fixture(with_prior_output=None)
		run, _ = _replay(suite)
		# The RESULT is an explicit Error (run-level "Error" stays reserved
		# for suite-level crashes per the merged 5-01 design); the case is
		# counted in the totals, not silently skipped.
		self.assertEqual(run.results[0].status, "Error")
		self.assertIn("Nothing to replay", run.results[0].error_message)
		self.assertEqual(run.total_cases, 1)
		self.assertEqual(run.failed_cases, 1)

	# ── Scenario 3: zero tokens/cost for case execution ──

	def test_replay_totals_are_zero_without_judge(self):
		suite, _ = _fixture(
			with_prior_output="hello world",
			assertion={"assertion_type": "contains", "value": "hello"},
		)
		run, _ = _replay(suite)
		self.assertEqual(run.total_tokens, 0)
		self.assertEqual(run.total_cost, 0)

	# ── Scenario 4: same realtime completion event as live ──

	def test_replay_fires_same_completion_event(self):
		suite, _ = _fixture(
			with_prior_output="hello world",
			assertion={"assertion_type": "contains", "value": "hello"},
		)
		run, publish = _replay(suite)
		events = _eval_events(publish)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].args[1]["run_name"], run.name)

	# ── Entry validation ──

	def test_run_eval_suite_validates_backend(self):
		suite, _ = _fixture(with_prior_output=None)
		with self.assertRaises(frappe.ValidationError):
			eval_runner.run_eval_suite(suite.name, backend="time_travel")

	def test_run_eval_suite_accepts_replay(self):
		suite, _ = _fixture(with_prior_output=None)
		with patch.object(frappe, "enqueue"):
			run_name = eval_runner.run_eval_suite(suite.name, backend="replay")
		self.assertEqual(frappe.db.get_value("AI Eval Run", run_name, "backend"), "replay")
