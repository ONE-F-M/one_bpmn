# Copyright (c) 2026, one-fm and contributors
# Backoff delay shared by the direct API executor and the step loop.

from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.agent_runtime import backoff_seconds


class TestBackoffSeconds(FrappeTestCase):
	def test_doubles_per_attempt_with_small_jitter(self):
		self.assertTrue(2.0 <= backoff_seconds(2, 500) <= 2.1)

	def test_cap_applies_before_jitter(self):
		self.assertTrue(5.0 <= backoff_seconds(3, 1000, 5.0) <= 5.1)
