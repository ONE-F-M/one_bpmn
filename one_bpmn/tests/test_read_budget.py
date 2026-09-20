# Copyright (c) 2026, one-fm and contributors
"""read_budget_exceeded: caps unbounded read_file/list_files exploration that
never attempts an edit, regardless of which files it wanders across.

Confirmed live (2026-09-13/14): a per-file re-read cap alone just pushed a
stuck run to explore dozens of *different* unrelated files instead of one —
still zero edit_file/write_file calls. This is the general case: a budget on
total unproductive reads, not on repeats of any one path."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import (
	_READ_BUDGET,
	read_budget_exceeded,
)


def _row(instance_name, action, state="completed"):
	row = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": state,
		"target_app": "one_bpmn",
		"git_branch": "staging",
		"bpmn_id": action,
		"caller_instance": instance_name,
		"request_payload": json.dumps({"action": action, "args": {}}),
	})
	row.flags.ignore_links = True
	row.insert(ignore_permissions=True)
	return row.name


class TestReadBudgetExceeded(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_instance_never_blocks(self):
		self.assertIsNone(read_budget_exceeded(None))

	def test_under_budget_is_fine(self):
		inst = frappe._dict(name="i-under")
		for _ in range(_READ_BUDGET - 1):
			_row(inst.name, "read_file")
		self.assertIsNone(read_budget_exceeded(inst))

	def test_at_budget_is_refused(self):
		inst = frappe._dict(name="i-at")
		for _ in range(_READ_BUDGET):
			_row(inst.name, "read_file")
		error = read_budget_exceeded(inst)
		self.assertIsNotNone(error)
		self.assertIn(str(_READ_BUDGET), error)
		self.assertIn("attempting a single edit", error)

	def test_list_files_and_read_file_share_one_budget(self):
		inst = frappe._dict(name="i-mixed")
		for i in range(_READ_BUDGET):
			_row(inst.name, "list_files" if i % 2 else "read_file")
		self.assertIsNotNone(read_budget_exceeded(inst))

	def test_an_edit_attempt_resets_the_budget(self):
		"""Confirmed live: the real failure mode is reads piling up with no
		edit attempt in between — a genuine edit call, even a failed one,
		means the model is trying, and further reads after it get a fresh
		budget rather than compounding with reads from before."""
		inst = frappe._dict(name="i-reset")
		for _ in range(_READ_BUDGET):
			_row(inst.name, "read_file")
		_row(inst.name, "edit_file")
		for _ in range(_READ_BUDGET - 1):
			_row(inst.name, "read_file")
		self.assertIsNone(read_budget_exceeded(inst))

	def test_a_failed_edit_still_resets_the_budget(self):
		"""state on the row reflects whether the sandbox call succeeded, not
		whether the edit itself matched — a failed edit_file (e.g. "old_string
		not found") still shows the model attempting one, which is the signal
		this function looks for."""
		inst = frappe._dict(name="i-failed-edit")
		for _ in range(_READ_BUDGET):
			_row(inst.name, "read_file")
		_row(inst.name, "edit_file")  # dispatch still "completed" even if the edit itself errored
		for _ in range(_READ_BUDGET - 1):
			_row(inst.name, "read_file")
		self.assertIsNone(read_budget_exceeded(inst))

	def test_another_instances_reads_do_not_count(self):
		inst = frappe._dict(name="i-mine")
		for _ in range(_READ_BUDGET):
			_row("i-someone-else", "read_file")
		self.assertIsNone(read_budget_exceeded(inst))
