# Copyright (c) 2026, one-fm and contributors
"""A sandbox run records what it was, for which Work Item, and when it ended."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.agent_sandbox_run.agent_sandbox_run import (
	ERROR_LIMIT,
	TERMINAL_STATES,
	bounded_error,
	identity_from_payload,
)
from one_bpmn.one_bpmn.patches.v1_0 import agent_sandbox_run_columns_from_request_payload as backfill


def _run(**fields):
	doc = frappe.get_doc({"doctype": "Agent Sandbox Run", "state": "running", "target_app": "one_bpmn", **fields})
	doc.insert(ignore_permissions=True)
	return doc


class TestTheRunRecord(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_new_run_has_a_start_time(self):
		self.assertTrue(_run().started_at)

	def test_every_ending_state_sets_the_end_time_and_a_running_one_does_not(self):
		for state in TERMINAL_STATES:
			run = _run()
			run.state = state
			run.save(ignore_permissions=True)
			self.assertTrue(run.completed_at, state)
		self.assertFalse(_run().completed_at)

	def test_the_new_states_are_valid(self):
		for state in ("stale", "timed_out", "cancelled"):
			run = _run()
			run.state = state
			run.save(ignore_permissions=True)

	def test_the_columns_come_from_the_request_payload_when_they_are_blank(self):
		payload = frappe.as_json({"action": "edit_file", "work_item_id": "WI-001", "agent_name": "Dev Agent"})
		run = _run(request_payload=payload)
		self.assertEqual((run.action, run.work_item, run.agent_name), ("edit_file", "WI-001", "Dev Agent"))

	def test_a_column_set_directly_is_not_overwritten_by_the_payload(self):
		run = _run(action="run_tests", request_payload=frappe.as_json({"action": "edit_file"}))
		self.assertEqual(run.action, "run_tests")

	def test_a_payload_with_no_identity_leaves_the_columns_blank(self):
		self.assertEqual(identity_from_payload(frappe.as_json({"args": {}})), {})
		self.assertEqual(identity_from_payload(None), {})

	def test_the_failure_class_only_takes_the_known_values(self):
		run = _run()
		run.failure_class = "made-up"
		with self.assertRaises(frappe.ValidationError):
			run.save(ignore_permissions=True)

	def test_the_commands_table_holds_a_command(self):
		run = _run()
		run.append("commands", {"sequence": 1, "action": "read_file", "status": "ok", "duration_ms": 40})
		run.save(ignore_permissions=True)
		self.assertEqual(frappe.get_doc("Agent Sandbox Run", run.name).commands[0].action, "read_file")


class TestBoundedError(FrappeTestCase):
	def test_a_short_error_is_kept_whole(self):
		self.assertEqual(bounded_error("boom"), "boom")

	def test_a_long_traceback_keeps_the_exception_line_at_its_end(self):
		trace = "Traceback (most recent call last):\n" + 'File "a.py", line 1, in f\n' * 400 + "ValueError: the real cause"
		out = bounded_error(trace)
		self.assertLessEqual(len(out), ERROR_LIMIT)
		self.assertTrue(out.endswith("ValueError: the real cause"))
		self.assertTrue(out.startswith("..."))

	def test_nothing_gives_an_empty_string(self):
		self.assertEqual(bounded_error(None), "")


class TestBackfill(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_old_rows_get_their_columns_and_a_second_run_changes_nothing(self):
		old = _run(request_payload=frappe.as_json({"action": "read_file", "work_item_id": "WI-9"}))
		frappe.db.set_value("Agent Sandbox Run", old.name, {"action": None, "work_item": None})

		backfill.execute()
		backfill.execute()

		row = frappe.db.get_value("Agent Sandbox Run", old.name, ["action", "work_item"], as_dict=True)
		self.assertEqual((row.action, row.work_item), ("read_file", "WI-9"))
