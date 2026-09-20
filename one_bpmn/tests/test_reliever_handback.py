# Copyright (c) 2026, one-fm and contributors
"""Giving a relieved owner their task back when they return from leave.

The redirect to a reliever already existed, but nothing recorded whose task it
had been, so it stayed with the reliever for good. These cover the record kept
at redirect time and the hand-back that reads it.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import (
	_swap_user,
	get_reliever_if_on_leave,
	restore_tasks_on_return,
)


class TestRedirectIsRecorded(FrappeTestCase):
	def test_a_redirect_reports_who_it_took_the_task_from(self):
		pairs = []
		with patch.object(frappe.db, "get_value", side_effect=["EMP-1", "bob@x.com"]):
			self.assertEqual(get_reliever_if_on_leave("alice@x.com", pairs), "bob@x.com")
		self.assertEqual(pairs, [("alice@x.com", "bob@x.com")])

	def test_nothing_is_recorded_when_nobody_is_on_leave(self):
		pairs = []
		with patch.object(frappe.db, "get_value", side_effect=["EMP-1", None]):
			self.assertEqual(get_reliever_if_on_leave("alice@x.com", pairs), "alice@x.com")
		self.assertEqual(pairs, [])

	def test_the_collector_stays_optional(self):
		with patch.object(frappe.db, "get_value", side_effect=["EMP-1", "bob@x.com"]):
			self.assertEqual(get_reliever_if_on_leave("alice@x.com"), "bob@x.com")


class TestSwapUser(FrappeTestCase):
	"""assigned_user carries every assignee of a Table Field task. A hand-back
	touches one entry; the others never went anywhere."""

	def test_only_the_reliever_entry_changes_hands(self):
		self.assertEqual(
			_swap_user("carl@x.com,bob@x.com,dina@x.com", "bob@x.com", "alice@x.com"),
			"carl@x.com,alice@x.com,dina@x.com",
		)

	def test_position_is_kept(self):
		self.assertEqual(_swap_user("bob@x.com,carl@x.com", "bob@x.com", "alice@x.com"),
		                 "alice@x.com,carl@x.com")

	def test_a_single_assignee_swaps_whole(self):
		self.assertEqual(_swap_user("bob@x.com", "bob@x.com", "alice@x.com"), "alice@x.com")

	def test_an_absent_reliever_changes_nothing(self):
		self.assertEqual(_swap_user("carl@x.com", "bob@x.com", "alice@x.com"), "carl@x.com")

	def test_an_owner_already_present_changes_nothing(self):
		"""The guard that makes a second run a no-op — the history stays on the
		row, so the query keeps matching and only this stops it repeating."""
		self.assertEqual(
			_swap_user("alice@x.com,carl@x.com", "bob@x.com", "alice@x.com"),
			"alice@x.com,carl@x.com",
		)

	def test_spacing_is_tolerated(self):
		self.assertEqual(_swap_user("carl@x.com, bob@x.com", "bob@x.com", "alice@x.com"),
		                 "carl@x.com,alice@x.com")


def _row(**kw):
	base = {
		"name": "row-1",
		"parent": "PI-1",
		"assigned_user": "bob@x.com",
		"relieved_user": "alice@x.com",
		"reliever_user": "bob@x.com",
	}
	base.update(kw)
	return frappe._dict(base)


class TestRestoreTasksOnReturn(FrappeTestCase):
	def _run(self, rows, user="alice@x.com"):
		"""Run the sweep over *rows*, returning (count, writes)."""
		writes = []
		# An instance with no context document: add/remove_frappe_assignment both
		# return early, so these stay about the row rewrite.
		instance = frappe._dict(name="PI-1", context_doctype="", context_docname="")
		with patch.object(frappe.db, "sql", return_value=rows), patch.object(
			frappe.db, "set_value", side_effect=lambda *a: writes.append(a)
		), patch.object(frappe.db, "get_value", return_value=""), patch(
			"frappe.get_doc", return_value=instance
		):
			return restore_tasks_on_return(user), writes

	def test_the_task_goes_back_to_its_owner(self):
		count, writes = self._run([_row()])
		self.assertEqual(count, 1)
		self.assertEqual(writes[0], ("BPMN Active Task", "row-1", "assigned_user", "alice@x.com"))

	def test_only_the_owners_own_entry_moves(self):
		count, writes = self._run([_row(assigned_user="carl@x.com,bob@x.com")])
		self.assertEqual(count, 1)
		self.assertEqual(writes[0][3], "carl@x.com,alice@x.com")

	def test_the_matching_reliever_is_picked_from_the_parallel_list(self):
		row = _row(
			assigned_user="bob@x.com,erin@x.com",
			relieved_user="dina@x.com,alice@x.com",
			reliever_user="erin@x.com,bob@x.com",
		)
		count, writes = self._run([row])
		self.assertEqual(count, 1)
		self.assertEqual(writes[0][3], "alice@x.com,erin@x.com")

	def test_running_twice_writes_once(self):
		"""The history is deliberately left on the row, so the query still finds
		it. The guard is what makes the second pass do nothing."""
		count, writes = self._run([_row(assigned_user="alice@x.com")])
		self.assertEqual((count, writes), (0, []))

	def test_a_row_naming_someone_else_is_left_alone(self):
		count, writes = self._run([_row(relieved_user="dina@x.com", reliever_user="bob@x.com")])
		self.assertEqual((count, writes), (0, []))

	def test_a_half_written_pair_is_skipped_not_guessed(self):
		count, writes = self._run([_row(reliever_user="")])
		self.assertEqual((count, writes), (0, []))

	def test_no_user_no_query(self):
		with patch.object(frappe.db, "sql") as sql:
			self.assertEqual(restore_tasks_on_return(""), 0)
		sql.assert_not_called()
