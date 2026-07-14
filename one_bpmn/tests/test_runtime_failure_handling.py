# Copyright (c) 2026, one-fm and contributors
"""
Tests for BPMN runtime failure handling (spec 2.2 + 2.4).

Covers the sanitized-error / Reference-ID / halt contract on
``BPMNProcessInstance``:
  * a runtime engine failure marks the instance "Errored" (halt — never
    silently proceed past a control gate);
  * the full traceback + context is written to admin-only sinks under a random
    Reference ID; and
  * the caller receives only a generic message + that Reference ID, never the
    raw exception internals (no schema names / permission walls / keyword hints).

Requires a Frappe bench (DB). Run with:
  bench --site <site> run-tests --app one_bpmn --module \
    one_bpmn.tests.test_runtime_failure_handling
"""

import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

_REF_ID_RE = re.compile(r"[0-9A-F]{12}")


class TestRuntimeFailureHandling(FrappeTestCase):
	def _make_instance(self):
		inst = frappe.new_doc("BPMN Process Instance")
		inst.name = "TEST-RUNTIME-FAIL-INSTANCE"
		inst.process_model = "TEST-MODEL"
		inst.status = "Active"
		return inst

	def test_record_runtime_failure_halts_instance(self):
		inst = self._make_instance()
		with patch.object(frappe.db, "set_value") as m_set, \
			patch.object(frappe.db, "commit") as m_commit, \
			patch.object(inst, "_log_task") as m_log:
			try:
				raise ValueError("tabUser secret schema — exec blocked keyword")
			except Exception:
				ref_id = inst._record_runtime_failure(phase="start")

		# A Reference ID is minted and the instance is halted durably.
		self.assertRegex(ref_id, r"^[0-9A-F]{12}$")
		self.assertEqual(inst.status, "Errored")
		m_set.assert_any_call(
			"BPMN Process Instance", inst.name, "status", "Errored",
			update_modified=False,
		)
		# Committed so the Errored state survives the sanitized re-raise's rollback.
		self.assertTrue(m_commit.called)
		# An admin-only activity row records the failure under the same Reference ID.
		self.assertTrue(m_log.called)
		_, kwargs = m_log.call_args
		self.assertEqual(kwargs.get("action"), "Errored")
		self.assertEqual(kwargs["data"]["reference_id"], ref_id)

	def test_record_runtime_failure_writes_admin_error_log(self):
		inst = self._make_instance()
		with patch.object(frappe.db, "set_value"), \
			patch.object(frappe.db, "commit"), \
			patch.object(inst, "_log_task"), \
			patch.object(frappe, "log_error") as m_err:
			try:
				raise ValueError("tabUser secret schema")
			except Exception:
				ref_id = inst._record_runtime_failure(phase="advance")

		# The deep log carries the Reference ID and the full traceback (admin-only).
		self.assertTrue(m_err.called)
		_, kwargs = m_err.call_args
		self.assertIn(ref_id, kwargs["title"])
		self.assertIn(ref_id, kwargs["message"])
		self.assertIn("Traceback", kwargs["message"])

	def test_fail_runtime_raises_sanitized_without_leak(self):
		inst = self._make_instance()
		secret = "tabUser permission wall — exec getattr keyword"
		with patch.object(frappe.db, "set_value"), \
			patch.object(frappe.db, "commit"), \
			patch.object(inst, "_log_task"):
			with self.assertRaises(frappe.ValidationError) as ctx:
				try:
					raise ValueError(secret)
				except Exception:
					inst._fail_runtime(phase="advance")

		msg = str(ctx.exception)
		# Generic message carries the Reference ID …
		self.assertRegex(msg, _REF_ID_RE)
		# … but never the raw exception internals.
		self.assertNotIn("tabUser", msg)
		self.assertNotIn("permission wall", msg)
		self.assertNotIn("getattr", msg)
