# Copyright (c) 2026, one-fm and contributors
"""One eval run per suite, agent and backend at a time."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_agent_configuration, make_eval_case, make_eval_suite
from one_bpmn.agents.eval_runner import run_eval_cases, run_eval_comparison, run_eval_suite


class TestOneRunPerSuite(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite()
		make_eval_case(suite=self.suite.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _runs(self):
		return frappe.get_all("AI Eval Run", filters={"suite": self.suite.name}, pluck="name")

	def test_run_eval_suite_twice_returns_the_running_run_and_enqueues_once(self):
		with patch.object(frappe, "enqueue") as enqueue:
			first = run_eval_suite(self.suite.name)
			second = run_eval_suite(self.suite.name)

		self.assertEqual(second, first)
		self.assertEqual(self._runs(), [first])
		self.assertEqual(enqueue.call_count, 1)
		self.assertEqual(enqueue.call_args.kwargs["job_id"], f"eval-run::{first}")
		self.assertTrue(enqueue.call_args.kwargs["deduplicate"])

	def test_run_eval_cases_twice_returns_the_running_run_and_enqueues_once(self):
		with patch.object(frappe, "enqueue") as enqueue:
			first = run_eval_cases(self.suite.name)
			second = run_eval_cases(self.suite.name)

		self.assertEqual(second, first)
		self.assertEqual(self._runs(), [first])
		self.assertEqual(enqueue.call_count, 1)

	def test_a_running_run_past_its_deadline_is_not_reused(self):
		with patch.object(frappe, "enqueue"):
			stale = run_eval_suite(self.suite.name)
			frappe.db.set_value(
				"AI Eval Run", stale, "started_at", add_to_date(now_datetime(), days=-1), update_modified=False
			)
			fresh = run_eval_suite(self.suite.name)

		self.assertNotEqual(fresh, stale)
		self.assertEqual(sorted(self._runs()), sorted([stale, fresh]))

	def test_a_running_run_for_another_backend_is_not_reused(self):
		with patch.object(frappe, "enqueue"):
			live = run_eval_suite(self.suite.name, backend="live")
			replay = run_eval_suite(self.suite.name, backend="replay")

		self.assertNotEqual(replay, live)

	def test_comparison_still_creates_two_runs_while_the_suite_is_running(self):
		challenger = make_agent_configuration().name
		with patch.object(frappe, "enqueue") as enqueue:
			running = run_eval_suite(self.suite.name)
			compared = run_eval_comparison(self.suite.name, agent_b=challenger)

		self.assertNotIn(running, (compared["run_a"], compared["run_b"]))
		self.assertNotEqual(compared["run_a"], compared["run_b"])
		self.assertEqual(len(self._runs()), 3)
		self.assertEqual(enqueue.call_count, 3)

	def test_a_user_who_cannot_read_the_suite_gets_a_permission_error_not_the_run(self):
		with patch.object(frappe, "enqueue"):
			run_eval_suite(self.suite.name)
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				run_eval_cases(self.suite.name)
