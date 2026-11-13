# Copyright (c) 2026, one-fm and contributors
"""The nightly model rate job: its scheduler entry resolves, and a failure is logged, not raised."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_observability.model_rates import apply_due_model_rates

JOB = "processa.ai_agent_observability.model_rates.apply_due_model_rates"
CATALOGUE = "processa.patches.v1_0.seed_ai_model_catalogue.apply_due_rates"


class TestModelRatesJob(FrappeTestCase):
	def test_the_scheduler_entry_points_at_the_new_module(self):
		scheduled = [job for jobs in frappe.get_hooks("scheduler_events")["cron"].values() for job in jobs]
		self.assertIn(JOB, scheduled)
		self.assertNotIn("processa.tasks.apply_due_model_rates", scheduled)
		self.assertTrue(callable(frappe.get_attr(JOB)))

	def test_a_failure_is_logged_and_not_raised(self):
		with patch(CATALOGUE, side_effect=RuntimeError("catalogue broke")), patch("frappe.log_error") as log:
			apply_due_model_rates()
		log.assert_called_once()
		self.assertEqual(log.call_args.kwargs["title"], "Model rate update failed")

	def test_each_applied_rate_is_logged(self):
		logger = patch("frappe.logger")
		with patch(CATALOGUE, return_value=["Model A 1.0 to 2.0"]), logger as get_logger:
			apply_due_model_rates()
		get_logger.return_value.info.assert_called_once_with("AI Model rate applied: Model A 1.0 to 2.0")
