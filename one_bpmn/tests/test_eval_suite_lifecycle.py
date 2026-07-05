# Copyright (c) 2026, one-fm and contributors
# WI-001361 (5-01): AI Eval Suite runner — gap closure against the runner
# already merged on staging: an unexpected exception partway through the
# suite must finalise the Run as Error (with partial data) and still fire
# the realtime completion event.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import eval_runner

test_ignore = ["AI Eval Suite", "AI Eval Case"]


def _eval_events(publish):
	return [c for c in publish.call_args_list if c.args and c.args[0] == "eval_run_completed"]


def _suite_with_case():
	suite = frappe.get_doc(
		{
			"doctype": "AI Eval Suite",
			"title": f"Lifecycle Suite {frappe.generate_hash(length=5)}",
		}
	)
	suite.flags.ignore_mandatory = True
	suite.insert(ignore_permissions=True, ignore_mandatory=True)

	case = frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"title": "case-1",
			"suite": suite.name,
			"backend": "direct_api",
			"input_user_prompt": "hello",
		}
	)
	case.flags.ignore_mandatory = True
	case.insert(ignore_permissions=True, ignore_mandatory=True)
	return suite, case


def _make_run(suite):
	run = frappe.new_doc("AI Eval Run")
	run.suite = suite.name
	run.status = "Running"
	run.backend = "live"
	run.started_at = frappe.utils.now_datetime()
	run.flags.ignore_mandatory = True
	run.insert(ignore_permissions=True, ignore_mandatory=True)
	return run


class TestEvalSuiteLifecycle(FrappeTestCase):
	# ── Scenario 4: happy path — rollups + realtime event ──

	def test_completed_suite_fires_event_with_rollups(self):
		suite, case = _suite_with_case()
		run = _make_run(suite)
		with (
			patch.object(
				eval_runner,
				"_execute_case",
				return_value={"eval_case": case.name, "status": "Passed", "cost": 0.5, "tokens_used": 10},
			),
			patch.object(frappe, "publish_realtime") as publish,
		):
			eval_runner._execute_eval_suite(run.name)

		saved = frappe.get_doc("AI Eval Run", run.name)
		self.assertEqual(saved.status, "Passed")
		self.assertEqual(saved.total_cases, 1)
		self.assertEqual(saved.passed_cases, 1)
		self.assertEqual(saved.total_tokens, 10)
		events = _eval_events(publish)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].args[1]["status"], "Passed")

	# ── Scenario 5: exception partway → Error + event still fires ──

	def test_suite_exception_finalises_error_and_fires_event(self):
		suite, _ = _suite_with_case()
		run = _make_run(suite)
		with (
			patch.object(eval_runner, "_execute_case", side_effect=RuntimeError("boom")),
			patch.object(frappe, "publish_realtime") as publish,
		):
			eval_runner._execute_eval_suite(run.name)  # must not raise

		saved = frappe.get_doc("AI Eval Run", run.name)
		self.assertEqual(saved.status, "Error")
		self.assertIsNotNone(saved.ended_at)
		events = _eval_events(publish)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].args[1]["status"], "Error")

	# ── Scenario 1: whitelisted entry creates a Running run ──

	def test_run_eval_suite_creates_running_run_and_enqueues(self):
		suite, _ = _suite_with_case()
		with patch.object(frappe, "enqueue") as enqueue:
			run_name = eval_runner.run_eval_suite(suite.name)
		run = frappe.get_doc("AI Eval Run", run_name)
		self.assertEqual(run.status, "Running")
		self.assertIsNotNone(run.started_at)
		enqueue.assert_called_once()
