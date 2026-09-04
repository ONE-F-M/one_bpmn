# Copyright (c) 2026, one-fm and contributors
# See license.txt
"""
WI-002325: a Script Task that says no is working, not failing.

A validation script calls ``frappe.throw`` when the process may not go on - a missing PAM
reference, an unfilled work permit number. The engine treated that as a runtime fault: it
marked the instance Errored and committed it, wrote two Error Log entries, and replaced
the script's message with "quote Reference ID ...". The operator was left with a stuck
visa request and no idea which field to fill.

What these pin is the discrimination itself, because getting it wrong in either direction
is silent: too narrow and validations go on halting processes; too broad and a genuine
crash stops being logged and stops halting anything.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from one_bpmn.one_bpmn.engine import is_script_validation


class TestWhatCountsAsAValidation(FrappeTestCase):
	"""frappe.throw() raises exactly ValidationError; every framework fault raises a
	subclass of it. The exact type is the whole discriminator."""

	def _raised(self, fn):
		try:
			fn()
		except Exception as exc:
			return exc
		raise AssertionError("nothing was raised")

	def test_a_plain_throw_is_a_validation(self):
		exc = self._raised(lambda: frappe.throw("Work Permit Number Required"))

		self.assertTrue(is_script_validation(exc))

	def test_a_missing_document_is_not(self):
		"""A script reaching for a document that is not there is a fault, and must still
		halt the instance and be logged."""
		exc = self._raised(
			lambda: frappe.throw("gone", frappe.DoesNotExistError)
		)

		self.assertFalse(is_script_validation(exc))

	def test_a_mandatory_field_error_is_not(self):
		exc = self._raised(lambda: frappe.throw("mandatory", frappe.MandatoryError))

		self.assertFalse(is_script_validation(exc))

	def test_a_permission_error_is_not(self):
		exc = self._raised(lambda: frappe.throw("denied", frappe.PermissionError))

		self.assertFalse(is_script_validation(exc))

	def test_an_ordinary_crash_is_not(self):
		exc = self._raised(lambda: 1 / 0)

		self.assertFalse(is_script_validation(exc))

	def test_a_link_validation_error_is_not(self):
		"""LinkValidationError subclasses ValidationError, which is exactly why the check
		is on the exact type rather than isinstance."""
		self.assertTrue(issubclass(frappe.LinkValidationError, frappe.ValidationError))
		exc = self._raised(lambda: frappe.throw("bad link", frappe.LinkValidationError))

		self.assertFalse(is_script_validation(exc))

	def test_an_agent_refusal_is_not_claimed_by_this_check(self):
		"""It is a ValidationError subclass too, and the engine already handles it on its
		own terms just above."""
		from one_bpmn.security.refusal import AgentRefusal

		self.assertTrue(issubclass(AgentRefusal, frappe.ValidationError))
		exc = self._raised(lambda: frappe.throw("refused", AgentRefusal))

		self.assertFalse(is_script_validation(exc))


class TestTheScriptRunnerDoesNotLogAValidation(FrappeTestCase):
	"""114 of these were written to the analyst's Error Log, every one a validation an
	operator was supposed to read and act on."""

	def _run_script(self, body):
		from SpiffWorkflow.bpmn.script_engine import TaskDataEnvironment

		from one_bpmn.one_bpmn.engine import FrappeScriptEngine

		engine = FrappeScriptEngine(
			TaskDataEnvironment(),
			script_task_extensions={},
			initiated_by=frappe.session.user,
		)

		task = MagicMock()
		task.data = {}

		script_doc = frappe._dict({"script": body, "disabled": 0})
		with patch.object(frappe, "get_doc", return_value=script_doc):
			with patch.object(frappe, "log_error") as logged:
				try:
					engine._run_frappe_server_script("Test Script", task)
				except Exception as exc:
					return exc, logged
		return None, logged

	def test_a_validation_is_re_raised_without_being_logged(self):
		exc, logged = self._run_script('frappe.throw("Enter the Work Permit Number")')

		self.assertIsNotNone(exc)
		self.assertIn("Work Permit Number", str(exc))
		logged.assert_not_called()

	def test_the_operator_still_gets_the_scripts_own_words(self):
		exc, _ = self._run_script('frappe.throw("The following PAM details are required")')

		self.assertIn("PAM details are required", str(exc))

	def test_a_real_crash_is_still_logged(self):
		exc, logged = self._run_script("1 / 0")

		self.assertIsInstance(exc, ZeroDivisionError)
		logged.assert_called_once()

	def test_a_missing_document_is_still_logged(self):
		exc, logged = self._run_script('frappe.throw("gone", frappe.DoesNotExistError)')

		self.assertIsNotNone(exc)
		logged.assert_called_once()

	def test_a_script_that_does_not_throw_logs_nothing(self):
		exc, logged = self._run_script('result["ok"] = True')

		self.assertIsNone(exc)
		logged.assert_not_called()


class TestTheInstanceIsNotHalted(FrappeTestCase):
	"""The part that left a visa request stuck. _fail_runtime marks the instance Errored
	and COMMITS that, so a rollback does not undo it - the process stayed broken over a
	field the operator could have filled in and retried."""

	def _instance(self):
		doc = frappe.new_doc("BPMN Process Instance")
		doc.name = "WI-002325-TEST"
		return doc

	def _fail_with(self, exc_factory):
		"""Call _fail_runtime from inside a live except block, as the engine does."""
		doc = self._instance()
		with patch.object(doc, "_record_runtime_failure", return_value="REF123") as halted:
			try:
				try:
					exc_factory()
				except Exception:
					doc._fail_runtime(phase="advance")
			except Exception as raised:
				return raised, halted
		raise AssertionError("_fail_runtime returned without raising")

	def test_a_validation_passes_straight_through(self):
		raised, halted = self._fail_with(lambda: frappe.throw("Enter the Work Permit Number"))

		self.assertIn("Work Permit Number", str(raised))
		halted.assert_not_called()

	def test_the_reference_id_does_not_replace_the_message(self):
		"""What the operator saw instead of being told which field to fill."""
		raised, _ = self._fail_with(lambda: frappe.throw("The following PAM details are required"))

		self.assertIn("PAM details are required", str(raised))
		self.assertNotIn("Reference ID", str(raised))

	def test_a_real_fault_still_halts_the_instance(self):
		raised, halted = self._fail_with(lambda: 1 / 0)

		halted.assert_called_once()
		self.assertIn("Reference ID", str(raised))

	def test_a_missing_document_still_halts_the_instance(self):
		raised, halted = self._fail_with(
			lambda: frappe.throw("gone", frappe.DoesNotExistError)
		)

		halted.assert_called_once()

	def test_an_agent_refusal_still_passes_through(self):
		"""The behaviour this fix was modelled on must be untouched."""
		from one_bpmn.security.refusal import AgentRefusal

		raised, halted = self._fail_with(lambda: frappe.throw("refused", AgentRefusal))

		self.assertIsInstance(raised, AgentRefusal)
		halted.assert_not_called()
