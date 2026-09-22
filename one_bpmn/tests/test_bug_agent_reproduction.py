# Copyright (c) 2026, one-fm and contributors
"""reproduction_required_error: Bug Agent's (and Bug Programmer's) reproduce-
before-fix gate on edit_file/write_file. A non-test-file edit is refused
until this run shows a test file written, THEN a run_tests that actually
failed -- an unrelated pre-existing failure elsewhere in the suite must not
satisfy it, only a failure that came after a test was written this run."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import reproduction_required_error


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
