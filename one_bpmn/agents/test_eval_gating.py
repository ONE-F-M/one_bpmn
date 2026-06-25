# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for _check_eval_suite_gating in compilation.py.

Verifies advisory warnings during deployment for gating suites that
have passed, failed, never been run, or are not linked to the model.
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

	# ── AC (a): Last run passed → no warnings ─────────────────────────

	def test_passed_run_no_warning(self):
		"""_check_eval_suite_gating returns no warnings when the suite's
		last run passed."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		self._make_run(suite.name, status="Passed")
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 0)

	# ── AC (b): Last run failed → warning ─────────────────────────────

	def test_failed_run_produces_warning(self):
		"""_check_eval_suite_gating returns a warning when the suite's
		last run failed."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		self._make_run(suite.name, status="Failed")
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 1)
		self.assertIn("failed", suite_warnings[0])
		self.assertIn("Consider re-running", suite_warnings[0])

	# ── AC (c): Never been run → warning ──────────────────────────────

	def test_never_run_produces_warning(self):
		"""_check_eval_suite_gating returns a warning when the suite has
		never been run."""
		model = self._get_process_model()
		suite = self._make_suite(model)
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 1)
		self.assertIn("has never been run", suite_warnings[0])

	# ── AC (d): No suite linked → no warnings ─────────────────────────

	def test_no_linked_suites(self):
		"""No warnings are returned when no suite is linked to the model."""
		warnings = _check_eval_suite_gating("__nonexistent_model__")
		self.assertEqual(warnings, [])

	# ── Additional: Suite without gate_deployment → ignored ───────────

	def test_suite_without_gate_deployment(self):
		"""Suites with gate_deployment=False are ignored."""
		model = self._get_process_model()
		suite = self._make_suite(model, gate_deployment=0)
		warnings = _check_eval_suite_gating(model)
		suite_warnings = [w for w in warnings if suite.title in w]
		self.assertEqual(len(suite_warnings), 0)

	# ── Additional: Mixed suites ──────────────────────────────────────

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

		passed_warnings = [w for w in warnings if suite_passed.title in w]
		self.assertEqual(len(passed_warnings), 0)

		failed_warnings = [w for w in warnings if suite_failed.title in w]
		self.assertEqual(len(failed_warnings), 1)

		never_warnings = [w for w in warnings if suite_never.title in w]
		self.assertEqual(len(never_warnings), 1)
