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
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import (
	fix_unverified_error,
	repeat_run_tests_without_progress_error,
	reproduction_required_error,
)


COMPANY_TEST = "one_fm/tests/test_company.py"
THE_FAILING_TEST = {
	"failing_tests": ["test_it (one_fm.tests.test_company.TestCompany.test_it)"],
	"stderr_tail": "Traceback (most recent call last):\n  File \"x.py\", line 3\nAssertionError: 1 != 2",
}


def _row(instance_name, action, state="completed", path=None, result=None, args=None):
	args = args if args is not None else ({"path": path} if path else {})
	row = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": state,
		"target_app": "one_fm",
		"git_branch": "staging",
		"bpmn_id": action,
		"caller_instance": instance_name,
		"request_payload": json.dumps({"action": action, "args": args}),
		"result": json.dumps(result) if result is not None else None,
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
		_row(inst.name, "write_file", state="completed", path=COMPANY_TEST)
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		self.assertIsNone(reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py"))

	def test_a_passing_run_after_the_test_does_not_count(self):
		inst = frappe._dict(name="i-passed")
		_row(inst.name, "write_file", state="completed", path="one_fm/tests/test_company.py")
		_row(inst.name, "run_tests", state="completed")
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)

	def test_edit_file_to_a_test_path_also_counts_as_writing_the_test(self):
		inst = frappe._dict(name="i-edited-test")
		_row(inst.name, "edit_file", state="completed", path=COMPANY_TEST)
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		self.assertIsNone(reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py"))

	def test_another_instances_reproduction_does_not_count(self):
		inst = frappe._dict(name="i-mine")
		_row("i-someone-else", "write_file", state="completed", path=COMPANY_TEST)
		_row("i-someone-else", "run_tests", state="failed", result=THE_FAILING_TEST)
		error = reproduction_required_error(inst, "one_fm/setup/doctype/company/company.py")
		self.assertIsNotNone(error)


class TestTheReproductionHasToBeReal(FrappeTestCase):
	FIX = "one_fm/setup/doctype/company/company.py"

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _written(self, name, path=COMPANY_TEST, action="write_file", args=None):
		inst = frappe._dict(name=name)
		_row(name, action, state="completed", path=path, args=args)
		return inst

	def test_a_failure_of_some_other_test_does_not_reproduce_it(self):
		inst = self._written("i-other-test")
		other = {"failing_tests": ["test_x (one_fm.tests.test_other.TestOther.test_x)"], "stderr_tail": "AssertionError"}
		_row(inst.name, "run_tests", state="failed", result=other)
		error = reproduction_required_error(inst, self.FIX)
		self.assertIn("did not show your new test failing", error)

	def test_a_run_with_no_failing_test_named_does_not_reproduce_it(self):
		inst = self._written("i-no-names")
		_row(inst.name, "run_tests", state="failed", result={"failing_tests": [], "stderr_tail": "boom"})
		self.assertIn("did not show your new test failing", reproduction_required_error(inst, self.FIX))

	def test_a_new_test_that_fails_on_an_import_or_syntax_error_is_not_a_reproduction(self):
		for line in ("ModuleNotFoundError: No module named 'x'", "ImportError: cannot import name y", "SyntaxError: invalid syntax", "IndentationError: unexpected indent"):
			inst = self._written(f"i-setup-{line[:6]}")
			broken = {**THE_FAILING_TEST, "stderr_tail": f"Traceback (most recent call last):\n  File \"t.py\", line 1\n{line}"}
			_row(inst.name, "run_tests", state="failed", result=broken)
			self.assertIn("import or syntax error", reproduction_required_error(inst, self.FIX), line)

	def test_an_application_exception_counts_as_failing_for_the_bug(self):
		inst = self._written("i-app-error")
		raised = {**THE_FAILING_TEST, "stderr_tail": "Traceback (most recent call last):\n  File \"app.py\", line 9\nfrappe.exceptions.ValidationError: no company"}
		_row(inst.name, "run_tests", state="failed", result=raised)
		self.assertIsNone(reproduction_required_error(inst, self.FIX))

	def test_a_later_valid_failure_clears_an_earlier_bad_one(self):
		inst = self._written("i-second-try")
		_row(inst.name, "run_tests", state="failed", result={**THE_FAILING_TEST, "stderr_tail": "SyntaxError: invalid"})
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		self.assertIsNone(reproduction_required_error(inst, self.FIX))

	def test_a_failure_that_came_before_the_test_was_written_does_not_count(self):
		inst = frappe._dict(name="i-order")
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		_row(inst.name, "write_file", state="completed", path=COMPANY_TEST)
		self.assertIsNotNone(reproduction_required_error(inst, self.FIX))

	def test_a_test_written_through_apply_edits_counts(self):
		inst = self._written("i-batch", path=None, action="apply_edits", args={"edits": [{"path": COMPANY_TEST, "old_string": "a", "new_string": "b"}]})
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		self.assertIsNone(reproduction_required_error(inst, self.FIX))

	def test_the_test_is_matched_by_its_dotted_module_or_its_file_name(self):
		inst = self._written("i-names")
		by_name = {"failing_tests": ["test_it (test_company.TestCompany.test_it)"], "stderr_tail": "AssertionError"}
		_row(inst.name, "run_tests", state="failed", result=by_name)
		self.assertIsNone(reproduction_required_error(inst, self.FIX))


class TestTheFixHasToBeVerified(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_change_to_the_application_is_not_a_fix(self):
		inst = frappe._dict(name="i-no-fix")
		_row(inst.name, "write_file", path=COMPANY_TEST)
		self.assertIn("Make the fix first", fix_unverified_error(inst))

	def test_a_fix_with_no_passing_run_after_it_is_refused(self):
		inst = frappe._dict(name="i-unrun")
		_row(inst.name, "write_file", path=COMPANY_TEST)
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		_row(inst.name, "edit_file", path="one_fm/company.py")
		self.assertIn("see it pass", fix_unverified_error(inst))

	def test_a_passing_run_after_the_fix_clears_it(self):
		inst = frappe._dict(name="i-verified")
		_row(inst.name, "edit_file", path="one_fm/company.py")
		_row(inst.name, "run_tests", state="completed")
		self.assertIsNone(fix_unverified_error(inst))

	def test_a_passing_run_before_the_last_change_does_not_count(self):
		inst = frappe._dict(name="i-stale-pass")
		_row(inst.name, "edit_file", path="one_fm/company.py")
		_row(inst.name, "run_tests", state="completed")
		_row(inst.name, "edit_file", path="one_fm/company.py")
		self.assertIn("see it pass", fix_unverified_error(inst))

	def test_a_failing_run_after_the_fix_does_not_clear_it(self):
		inst = frappe._dict(name="i-still-failing")
		_row(inst.name, "edit_file", path="one_fm/company.py")
		_row(inst.name, "run_tests", state="failed", result=THE_FAILING_TEST)
		self.assertIsNotNone(fix_unverified_error(inst))

	def test_editing_only_a_test_after_a_pass_does_not_reset_it(self):
		inst = frappe._dict(name="i-test-after")
		_row(inst.name, "edit_file", path="one_fm/company.py")
		_row(inst.name, "run_tests", state="completed")
		_row(inst.name, "edit_file", path=COMPANY_TEST)
		self.assertIsNone(fix_unverified_error(inst))


class TestOnlyTheFlaggedAgentIsHeld(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _flag(self, name, value):
		if not frappe.db.exists("AI Agent Configuration", name):
			self.skipTest(f"{name} is not on this site")
		frappe.db.set_value("AI Agent Configuration", name, "require_reproduction", value, update_modified=False)

	def _dispatch(self, process_model, action="edit_file", args=None):
		instance = frappe._dict(name="i-held", process_model=process_model)
		with patch.object(ops, "dispatch_error", return_value=None), patch.object(
			ops, "frontend_edit_error", return_value=None
		), patch.object(ops, "_plan_gap_error", return_value=None), patch.object(frappe, "get_cached_doc", side_effect=_no_settings):
			return ops.sandbox_dispatch(action, "one_fm", "staging", "d", args or {"path": "one_fm/company.py"}, instance=instance)

	def test_a_flagged_agent_is_refused_a_non_test_edit_without_a_reproduction_and_needs_no_plan(self):
		self._flag("Bug Programmer", 1)
		self.assertIn("Reproduce the bug first", self._dispatch("Bug Programmer")["error"])

	def test_the_same_edit_is_not_held_for_an_agent_without_the_flag(self):
		self._flag("Dev Agent", 0)
		out = self._dispatch("Dev Agent")
		self.assertNotIn("Reproduce", out.get("error", ""))
		self.assertNotIn("Submit a plan", out.get("error", ""))

	def test_a_flagged_agent_may_always_write_a_test(self):
		self._flag("Bug Programmer", 1)
		out = self._dispatch("Bug Programmer", args={"path": COMPANY_TEST})
		self.assertNotIn("Reproduce", out.get("error", ""))

	def test_a_batch_with_a_non_test_file_in_it_is_held(self):
		self._flag("Bug Programmer", 1)
		edits = [{"path": COMPANY_TEST, "old_string": "a", "new_string": "b"}, {"path": "one_fm/company.py", "old_string": "a", "new_string": "b"}]
		self.assertIn("Reproduce the bug first", self._dispatch("Bug Programmer", "apply_edits", {"edits": edits})["error"])

	def test_the_pull_request_is_refused_until_the_fix_is_verified(self):
		self._flag("Bug Reviewer", 1)
		instance = frappe._dict(name="i-pr", process_model="Bug Reviewer")
		with patch.object(ops, "dispatch_error", return_value=None), self.assertRaises(ops.AgentSandboxError) as caught:
			ops.dispatch_action({"target_app": "one_fm", "git_branch": "staging", "work_item_description": "d"}, {"instance": instance, "task": None, "operation": "open_pull_request"})
		self.assertIn("Make the fix first", str(caught.exception))


_real_get_cached_doc = frappe.get_cached_doc


def _no_settings(doctype, *args, **kwargs):
	"""Processa Settings with no sandbox address, so a call that passes the gates stops harmlessly."""
	if doctype == "Processa Settings":
		return SimpleNamespace(agent_sandbox_url="", get_password=lambda *a, **k: "")
	return _real_get_cached_doc(doctype, *args, **kwargs)


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
