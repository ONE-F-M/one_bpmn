# Copyright (c) 2026, one-fm and contributors
"""The endpoints that start eval runs enqueue background jobs, so they take POST and typed arguments."""

import inspect

import frappe
from frappe.tests.utils import FrappeTestCase

import one_bpmn.ai_agent_evals.runner.cases as runner_cases
import one_bpmn.ai_agent_evals.runner.comparison as runner_comparison
import one_bpmn.ai_agent_evals.runner.suite as runner_suite

ENDPOINTS = (runner_suite.run_eval_suite, runner_cases.run_eval_cases, runner_comparison.run_eval_comparison)


class TestEvalRunEndpoints(FrappeTestCase):
	def test_each_endpoint_accepts_post_only(self):
		for fn in ENDPOINTS:
			with self.subTest(fn.__name__):
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])

	def test_every_argument_is_typed(self):
		for fn in ENDPOINTS:
			for name, param in inspect.signature(fn).parameters.items():
				with self.subTest(f"{fn.__name__}.{name}"):
					self.assertIsNot(param.annotation, inspect.Parameter.empty)
