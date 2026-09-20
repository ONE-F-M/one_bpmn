# Copyright (c) 2026, one-fm and contributors
"""The background job a suite runs in is allowed as long as the suite needs.

RQ kills a job at its timeout and the run saves its results once, at the end,
so a job that outgrows its timeout loses every result it collected. With a
fixed 1800 s, both hardened Baselines — 21 and 22 cases at pass_k 2 — died at
the half-hour mark twice on 2026-09-15 with nothing saved.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_suite
from one_bpmn.agents.eval_runner import MIN_JOB_TIMEOUT_SECONDS, SECONDS_PER_EXECUTION, _job_timeout


class TestEvalJobTimeoutFitsTheSuite(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(process_model=None, title="_Test job timeout " + frappe.generate_hash(length=6))

	def _pass_k(self, k):
		frappe.db.set_value("AI Eval Suite", self.suite.name, "pass_k", k)

	def test_a_small_suite_keeps_the_old_floor(self):
		self._pass_k(1)
		self.assertEqual(_job_timeout(self.suite.name, "live", 3), MIN_JOB_TIMEOUT_SECONDS)

	def test_a_suite_run_twice_per_case_gets_time_for_every_execution(self):
		"""22 cases at pass_k 2 is 44 executions — the shape that died at 1800 s."""
		self._pass_k(2)
		self.assertEqual(_job_timeout(self.suite.name, "live", 22), 44 * SECONDS_PER_EXECUTION)
		self.assertGreater(_job_timeout(self.suite.name, "live", 22), MIN_JOB_TIMEOUT_SECONDS)

	def test_a_replay_repeats_nothing_whatever_pass_k_says(self):
		self._pass_k(3)
		self.assertEqual(_job_timeout(self.suite.name, "replay", 22), max(MIN_JOB_TIMEOUT_SECONDS, 22 * SECONDS_PER_EXECUTION))
