# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the _check_eval_suite_gating function in compilation.py.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.api.compilation import _check_eval_suite_gating


class TestCheckEvalSuiteGating(FrappeTestCase):
	"""Tests for advisory eval suite gating during deployment."""

	def _get_process_model(self):
		"""Return an existing BPMN Process Model name for test isolation."""
		name = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not name:
			self.skipTest("No BPMN Process Model exists for testing")
		return name

	def _make_suite(self, process_model, gate_deployment=1):
		"""Create an AI Eval Suite with unique title."""
		doc = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": f"Gating Test Suite {frappe.generate_hash(length=6)}",
			"process_model": process_model,
			"gate_deployment": gate_deployment,
		})
		doc.insert(ignore_permissions=True)
		return doc

	def _make_run(self, suite_name, status="Passed"):
		"""Create an AI Eval Run record with given status."""
		doc = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": suite_name,
			"status": status,
			"started_at": now_datetime(),
			"backend": "live",
		})
		doc.insert(ignore_permissions=True)
		return doc

	# ── No linked suites → no warnings ────────────────────────────────

	def test_no_linked_suites(self):
		"""When no eval suites are linked, no warnings should be returned."""
		warnings = _check_eval_suite_gating("__nonexistent_model__")
		self.assertEqual(warnings, [])

	# ── Suite with gate_deployment=False → ignored ────────────────────

	def test_suite_without_gate_deployment(self):
		"""Suites without gate_deployment=True should be ignored."""
		model = self._get_process_model()
		suite = self._make_suite(model, gate_deployment=0)
		warnings = _check_eval_suite_gating(model)
		# The non-gating suite itself should not appear in any warning
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 0)

	# ── Gating suite with no runs → warning ──────────────────────────

	def test_no_runs_produces_warning(self):
		"""A gating suite with no AI Eval Run records should warn."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		warnings = _check_eval_suite_gating(model)
		# Should have at least one warning about never-run suite
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 1)
		self.assertIn("has never been run", suite_warnings[0])

	# ── Gating suite with last run Failed → warning ──────────────────

	def test_failed_run_produces_warning(self):
		"""A gating suite whose last run failed should produce a warning."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		self._make_run(suite.name, status="Failed")
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 1)
		self.assertIn("failed", suite_warnings[0])
		self.assertIn("Consider re-running", suite_warnings[0])

	# ── Gating suite with last run Passed → no warning ───────────────

	def test_passed_run_no_warning(self):
		"""A gating suite whose last run passed should produce no warning."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		self._make_run(suite.name, status="Passed")
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 0)

	# ── Multiple suites — mixed statuses ──────────────────────────────

	def test_multiple_suites_mixed(self):
		"""Multiple gating suites: only failed/never-run ones produce warnings."""
		model = self._get_process_model()
		suite_passed = self._make_suite(model)
		suite_failed = self._make_suite(model)
		suite_never = self._make_suite(model)

		self._make_run(suite_passed.name, status="Passed")
		self._make_run(suite_failed.name, status="Failed")
		# suite_never has no runs

		warnings = _check_eval_suite_gating(model)

		# Passed suite should NOT appear in warnings
		passed_warnings = [w for w in warnings if suite_passed.title in w]
		self.assertEqual(len(passed_warnings), 0)

		# Failed suite SHOULD appear
		failed_warnings = [w for w in warnings if suite_failed.title in w]
		self.assertEqual(len(failed_warnings), 1)

		# Never-run suite SHOULD appear
		never_warnings = [w for w in warnings if suite_never.title in w]
		self.assertEqual(len(never_warnings), 1)
