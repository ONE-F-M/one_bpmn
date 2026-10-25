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

	def test_fail_runtime_reraises_permission_error_with_message(self):
		inst = self._make_instance()
		message = "Only users with the role 'Employee' can perform this workflow action."
		with patch.object(frappe.db, "set_value") as m_set, \
			patch.object(frappe.db, "commit"), \
			patch.object(inst, "_log_task"), \
			patch.object(inst, "_record_runtime_failure") as m_record:
			with self.assertRaises(frappe.PermissionError) as ctx:
				try:
					raise frappe.PermissionError(message)
				except Exception:
					inst._fail_runtime(phase="advance")

		self.assertIn(message, str(ctx.exception))
		m_record.assert_not_called()
		m_set.assert_not_called()
		self.assertEqual(inst.status, "Active")

	def test_fail_runtime_permission_error_without_message_uses_fallback(self):
		inst = self._make_instance()
		with patch.object(frappe.db, "set_value") as m_set, \
			patch.object(frappe.db, "commit"), \
			patch.object(inst, "_log_task"), \
			patch.object(inst, "_record_runtime_failure") as m_record:
			with self.assertRaises(frappe.PermissionError) as ctx:
				try:
					raise frappe.PermissionError()
				except Exception:
					inst._fail_runtime(phase="advance")

		self.assertIn(
			"You do not have permission to complete this step. "
			"Ask your administrator for access, then try again.",
			str(ctx.exception),
		)
		m_record.assert_not_called()
		m_set.assert_not_called()
		self.assertEqual(inst.status, "Active")

	def test_fail_runtime_value_error_still_halts(self):
		inst = self._make_instance()
		with patch.object(frappe.db, "set_value"), \
			patch.object(frappe.db, "commit"), \
			patch.object(inst, "_log_task"), \
			patch.object(
				inst, "_record_runtime_failure", return_value="ABCDEF012345"
			) as m_record:
			with self.assertRaises(frappe.ValidationError) as ctx:
				try:
					raise ValueError("boom")
				except Exception:
					inst._fail_runtime(phase="advance")

		m_record.assert_called_once_with("advance")
		self.assertIn("ABCDEF012345", str(ctx.exception))
		self.assertNotIn("boom", str(ctx.exception))


class TestCompleteTaskPermissionError(FrappeTestCase):
	def _instance(self):
		instance = frappe.new_doc("BPMN Process Instance")
		instance.update({"process_id": f"test-{frappe.generate_hash(length=6)}", "status": "Active"})
		# Only the row matters here: the job reloads it by name and advance() is patched.
		instance.db_insert()
		return instance

	def _complete(self, instance, error):
		from one_bpmn.api import instance_api
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import BPMNProcessInstance

		with patch.object(BPMNProcessInstance, "advance", side_effect=error):
			instance_api._complete_task_job(
				instance_name=instance.name, task_id="approve", run_as_user=frappe.session.user
			)

	def test_a_permission_error_in_a_step_after_a_user_task_reaches_the_user(self):
		instance = self._instance()
		message = "Only users with the role 'Director' can perform this action."

		with self.assertRaises(frappe.PermissionError) as ctx:
			self._complete(instance, frappe.PermissionError(message))

		self.assertIn(message, str(ctx.exception))
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Active")

	def test_any_other_error_still_marks_the_instance_errored(self):
		instance = self._instance()

		self._complete(instance, ValueError("boom"))

		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Errored")
