# Copyright (c) 2026, one-fm and contributors
"""goal_reminder and plan_required_error: reducing the "explores forever,
never edits" failure mode with two complementary levers instead of only
capping how much it can read.

goal_reminder re-anchors the model on its actual work order once it has done
a while of exploring with nothing to show for it, re-derived from the A2A
Task's own instruction rather than trusted from the model's own arguments.
plan_required_error forces a concrete plan to be submitted before any file
is touched, so implementation starts from a stated approach rather than
being improvised one file at a time."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import (
	_PLAN_ACTION,
	_READ_BUDGET,
	_REMINDER_AFTER,
	goal_reminder,
	plan_required_error,
)


def _row(instance_name, action, state="completed", request_payload=None):
	row = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": state,
		"target_app": "one_bpmn",
		"git_branch": "staging",
		"bpmn_id": action,
		"caller_instance": instance_name,
		"request_payload": request_payload or json.dumps({"action": action, "args": {}}),
	})
	row.flags.ignore_links = True
	row.insert(ignore_permissions=True)
	return row.name


class TestGoalReminder(FrappeTestCase):
	"""No real A2A Task is ever inserted here — that doctype's insert is
	live-polled by a scheduled job that would dispatch the actual Dev Agent
	workflow (confirmed the hard way: a real Anthropic API call fired from
	an early version of this test that did insert one). _a2a_instruction is
	mocked instead — the one small, module-local lookup goal_reminder
	actually needs — rather than a global frappe.db.get_value patch, which
	was confirmed to leave later frappe.get_all calls in the same test run
	returning empty for unrelated reasons."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _instance(self, name):
		return frappe._dict(name=name, context_doctype="A2A Task", context_docname="A2A-fake")

	def _reminder(self, inst, instruction):
		with patch(
			"one_bpmn.one_bpmn.connectors.agent_sandbox_ops._a2a_instruction",
			return_value=instruction or "",
		):
			return goal_reminder(inst)

	def test_no_instance_never_reminds(self):
		self.assertIsNone(goal_reminder(None))

	def test_under_threshold_is_quiet(self):
		inst = self._instance("i-under")
		for _ in range(_REMINDER_AFTER - 1):
			_row(inst.name, "read_file")
		self.assertIsNone(self._reminder(inst, "Add terminal_tools to ExecutorConfig."))

	def test_at_threshold_reminds_with_the_real_instruction(self):
		inst = self._instance("i-at")
		for _ in range(_REMINDER_AFTER):
			_row(inst.name, "read_file")
		reminder = self._reminder(inst, "Do the specific thing that matters.")
		self.assertIsNotNone(reminder)
		self.assertIn("Do the specific thing that matters.", reminder)

	def test_an_edit_attempt_silences_the_reminder(self):
		inst = self._instance("i-edited")
		for _ in range(_REMINDER_AFTER):
			_row(inst.name, "read_file")
		_row(inst.name, "edit_file")
		self.assertIsNone(self._reminder(inst, "Add terminal_tools to ExecutorConfig."))

	def test_no_a2a_context_is_quiet_not_an_error(self):
		"""Not every caller of these tools is necessarily a Dev Agent run with
		an A2A Task context — degrade to silence, never raise."""
		inst = frappe._dict(name="i-no-context", context_doctype="Work Item", context_docname="WI-1")
		for _ in range(_REMINDER_AFTER):
			_row(inst.name, "read_file")
		self.assertIsNone(goal_reminder(inst))


class TestPlanRequiredError(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_instance_never_blocks(self):
		self.assertIsNone(plan_required_error(None))

	def test_no_plan_yet_is_refused(self):
		inst = frappe._dict(name="i-no-plan")
		error = plan_required_error(inst)
		self.assertIsNotNone(error)
		self.assertIn("submit_plan", error)

	def test_a_submitted_plan_clears_it(self):
		inst = frappe._dict(name="i-planned")
		_row(inst.name, _PLAN_ACTION, request_payload=json.dumps(
			{"action": _PLAN_ACTION, "args": {"plan": "Add a field, then wire the loop."}}
		))
		self.assertIsNone(plan_required_error(inst))

	def test_another_instances_plan_does_not_count(self):
		inst = frappe._dict(name="i-mine")
		_row("i-someone-else", _PLAN_ACTION)
		self.assertIsNotNone(plan_required_error(inst))

	def test_a_read_only_run_still_needs_a_plan(self):
		inst = frappe._dict(name="i-only-reads")
		for _ in range(_READ_BUDGET - 1):
			_row(inst.name, "read_file")
		self.assertIsNotNone(plan_required_error(inst))
