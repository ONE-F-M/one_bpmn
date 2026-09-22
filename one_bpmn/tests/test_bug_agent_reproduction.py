# Copyright (c) 2026, one-fm and contributors
"""Two Bug pipeline reliability gates in agent_sandbox_ops.py:

reproduction_required_error -- Bug Agent's (and Bug Programmer's) reproduce-
before-fix gate on edit_file/write_file. A non-test-file edit is refused
until this run shows a test file written, THEN a run_tests that actually
failed -- an unrelated pre-existing failure elsewhere in the suite must not
satisfy it, only a failure that came after a test was written this run.

repeat_run_tests_without_progress_error -- refuses a run_tests call for a
Bug pipeline agent when the single most recent Agent Sandbox Run for this
instance was itself a failed run_tests, i.e. nothing has been attempted
since the last failure. Confirmed live (WI-000433, A2A-165115): Bug
Programmer called run_tests four times in a row against the unmodified
suite and burned its whole turn budget without ever attempting an edit."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import (
	repeat_run_tests_without_progress_error,
	reproduction_required_error,
)


def _row(instance_name, action, state="completed", path=None):
	args = {"path": path} if path else {}
	row = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": state,
		"target_app": "one_fm",
		"git_branch": "staging",
		"bpmn_id": action,
		"caller_instance": instance_name,
		"request_payload": json.dumps({"action": action, "args": args}),
	})
	row.flags.ignore_links = True
	row.insert(ignore_permissions=True)
	return row.name


class TestReproductionRequiredError(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_instance_still_refuses_a_non_test_path(self):
		error = reproduction_required_error(None, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)

	def test_a_test_file_path_is_always_allowed(self):
		inst = frappe._dict(name="i-fresh")
		self.assertIsNone(reproduction_required_error(inst, "one_fm/tests/test_company.py"))

	def test_a_test_file_path_is_allowed_even_with_no_instance(self):
		self.assertIsNone(reproduction_required_error(None, "one_fm/tests/test_company.py"))

	def test_no_history_refuses_a_real_fix(self):
		inst = frappe._dict(name="i-no-history")
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)
		self.assertIn("Reproduce", error)

	def test_a_failure_with_no_test_ever_written_still_refuses(self):
		"""The loophole this gate exists to close: an unrelated, pre-existing
		failure in the untouched suite must not look like reproduction."""
		inst = frappe._dict(name="i-unrelated-failure")
		_row(inst.name, "run_tests", state="failed")
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)

	def test_test_written_then_failing_run_clears_it(self):
		inst = frappe._dict(name="i-reproduced")
		_row(inst.name, "write_file", state="completed", path="one_fm/tests/test_company.py")
		_row(inst.name, "run_tests", state="failed")
		self.assertIsNone(reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py"))

	def test_a_passing_run_after_the_test_does_not_count(self):
		inst = frappe._dict(name="i-passed")
		_row(inst.name, "write_file", state="completed", path="one_fm/tests/test_company.py")
		_row(inst.name, "run_tests", state="completed")
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)

	def test_edit_file_to_a_test_path_also_counts_as_writing_the_test(self):
		inst = frappe._dict(name="i-edited-test")
		_row(inst.name, "edit_file", state="completed", path="one_fm/tests/test_company.py")
		_row(inst.name, "run_tests", state="failed")
		self.assertIsNone(reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py"))

	def test_another_instances_reproduction_does_not_count(self):
		inst = frappe._dict(name="i-mine")
		_row("i-someone-else", "write_file", state="completed", path="one_fm/tests/test_company.py")
		_row("i-someone-else", "run_tests", state="failed")
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)


class TestRepeatRunTestsWithoutProgress(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _instance(self, name, process_model="Bug Programmer"):
		return frappe._dict(name=name, process_model=process_model)

	def test_no_instance_never_blocks(self):
		self.assertIsNone(repeat_run_tests_without_progress_error(None, "run_tests"))

	def test_only_guards_run_tests_not_other_actions(self):
		inst = self._instance("i-other-action")
		_row(inst.name, "run_tests", state="failed")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "edit_file"))

	def test_a_non_bug_pipeline_process_is_never_blocked(self):
		"""Dev Agent and the rest share this same dispatch path and are
		deliberately left untouched."""
		inst = self._instance("i-dev-agent", process_model="Dev Agent")
		_row(inst.name, "run_tests", state="failed")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))

	def test_first_run_tests_call_ever_is_allowed(self):
		inst = self._instance("i-first-call")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))

	def test_immediate_repeat_after_a_failure_is_refused(self):
		inst = self._instance("i-repeat")
		_row(inst.name, "run_tests", state="failed")
		error = repeat_run_tests_without_progress_error(inst, "run_tests")
		self.assertIsNotNone(error)

	def test_a_passing_run_is_never_treated_as_a_blocking_failure(self):
		inst = self._instance("i-passed")
		_row(inst.name, "run_tests", state="completed")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))

	def test_an_edit_after_the_failure_clears_it(self):
		inst = self._instance("i-edited-since")
		_row(inst.name, "run_tests", state="failed")
		_row(inst.name, "write_file", state="completed", path="one_fm/tests/test_company.py")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))

	def test_a_read_in_between_also_counts_as_real_investigation(self):
		"""Not a blind repeat -- re-reading before trying again is legitimate
		and must not be refused."""
		inst = self._instance("i-read-since")
		_row(inst.name, "run_tests", state="failed")
		_row(inst.name, "read_file", state="completed", path="one_fm/setup/doctype/company/company.py")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))

	def test_another_instances_failure_does_not_count(self):
		inst = self._instance("i-mine")
		_row("i-someone-else", "run_tests", state="failed")
		self.assertIsNone(repeat_run_tests_without_progress_error(inst, "run_tests"))
