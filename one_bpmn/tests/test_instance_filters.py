# Copyright (c) 2026, one-fm and contributors
# WI-001818 — "Initiated By" and "Pending Action By" filters on the Process
# Instance list.
#
# initiated_by is an ordinary field and rides the existing filters dict.
# pending_action_by is derived from the BPMN Active Task child rows, and the
# derivation is where the sharp edges are: assigned_user may hold a comma-joined
# list of people, an email can be a substring of another email, a role task
# counts only while it is unclaimed, and a Waiting row outlives its instance.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.instance_api import list_process_instances

test_ignore = ["BPMN Process Model"]

ROLE = "Test Pending Action Role"


def _user(email: str, roles: list = None) -> str:
	if not frappe.db.exists("User", email):
		doc = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": "System User",
		})
		doc.insert(ignore_permissions=True)
	if roles:
		doc = frappe.get_doc("User", email)
		for role in roles:
			if not any(r.role == role for r in doc.roles):
				doc.append("roles", {"role": role})
		doc.save(ignore_permissions=True)
	return email


class TestInstanceFilters(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert(
				ignore_permissions=True
			)

		# alice@… is deliberately a substring of malice@… — a bare LIKE on
		# assigned_user would hand alice's filter malice's instances.
		cls.alice = _user("alice@wi1818.test")
		cls.malice = _user("malice@wi1818.test")
		cls.bob = _user("bob@wi1818.test")
		cls.role_holder = _user("roleholder@wi1818.test", roles=[ROLE])

	def _instance(self, initiated_by: str, status: str = "Active", tasks: list = None):
		# No explicit cleanup: FrappeTestCase rolls the test's transaction back,
		# and an extra delete would only add lock contention on tabBPMN Active
		# Task, which the engine workers rewrite constantly on a live bench.
		doc = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"status": status,
			"initiated_by": initiated_by,
			"active_tasks": tasks or [],
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	@staticmethod
	def _task(**kwargs) -> dict:
		row = {
			"task_id": frappe.generate_hash(length=8),
			"task_name": "Approve",
			"task_type": "User Task",
			"status": "Waiting",
		}
		row.update(kwargs)
		return row

	def _names(self, **kwargs) -> set:
		return {d.name for d in list_process_instances(limit_page_length=100, **kwargs)}

	# ── initiated_by ─────────────────────────────────────────────────────────

	def test_initiated_by_returns_only_that_users_instances(self):
		mine = self._instance(self.alice)
		theirs = self._instance(self.bob)

		names = self._names(filters={"initiated_by": self.alice})

		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)

	# ── pending_action_by: direct assignment ─────────────────────────────────

	def test_pending_action_by_matches_direct_assignee(self):
		name = self._instance(self.bob, tasks=[self._task(assigned_user=self.alice)])

		self.assertIn(name, self._names(pending_action_by=self.alice))

	def test_pending_action_by_matches_member_of_comma_joined_assignees(self):
		"""Multi-assignee ("Table Field") mode stores a comma-joined list."""
		name = self._instance(
			self.bob,
			tasks=[self._task(assigned_user=f"{self.bob},{self.alice}")],
		)

		self.assertIn(name, self._names(pending_action_by=self.alice))

	def test_pending_action_by_does_not_match_on_substring(self):
		"""alice@… must not pick up malice@…'s task."""
		name = self._instance(self.bob, tasks=[self._task(assigned_user=self.malice)])

		self.assertNotIn(name, self._names(pending_action_by=self.alice))

	def test_pending_action_by_ignores_completed_rows(self):
		name = self._instance(
			self.bob,
			tasks=[self._task(assigned_user=self.alice, status="Completed")],
		)

		self.assertNotIn(name, self._names(pending_action_by=self.alice))

	# ── pending_action_by: role assignment ───────────────────────────────────

	def test_pending_action_by_matches_unclaimed_role_task(self):
		name = self._instance(self.bob, tasks=[self._task(assigned_role=ROLE)])

		self.assertIn(name, self._names(pending_action_by=self.role_holder))

	def test_pending_action_by_skips_claimed_role_task(self):
		"""Once a user is resolved onto the row, that field alone decides who
		owes the action — other role members no longer do."""
		name = self._instance(
			self.bob,
			tasks=[self._task(assigned_role=ROLE, assigned_user=self.alice)],
		)

		self.assertNotIn(name, self._names(pending_action_by=self.role_holder))
		self.assertIn(name, self._names(pending_action_by=self.alice))

	def test_pending_action_by_skips_role_the_user_does_not_hold(self):
		name = self._instance(self.bob, tasks=[self._task(assigned_role=ROLE)])

		self.assertNotIn(name, self._names(pending_action_by=self.alice))

	# ── pending_action_by: instance status ───────────────────────────────────

	def test_pending_action_by_excludes_non_active_instances(self):
		"""A Cancelled run keeps its Waiting rows; nothing there is actionable."""
		name = self._instance(
			self.bob,
			status="Cancelled",
			tasks=[self._task(assigned_user=self.alice)],
		)

		self.assertNotIn(name, self._names(pending_action_by=self.alice))

	def test_pending_action_by_with_no_matches_short_circuits(self):
		"""Nobody pending → an empty list, without querying instances at all."""
		self._instance(self.bob, tasks=[self._task(assigned_user=self.malice)])

		# Roles stripped so no real unclaimed role task on this site can match.
		nobody = _user("nobody@wi1818.test")
		doc = frappe.get_doc("User", nobody)
		doc.roles = []
		doc.save(ignore_permissions=True)

		self.assertEqual(list_process_instances(pending_action_by=nobody), [])

	# ── the two filters together ─────────────────────────────────────────────

	def test_filters_combine(self):
		both = self._instance(self.alice, tasks=[self._task(assigned_user=self.bob)])
		wrong_initiator = self._instance(
			self.malice, tasks=[self._task(assigned_user=self.bob)]
		)
		wrong_assignee = self._instance(
			self.alice, tasks=[self._task(assigned_user=self.malice)]
		)

		names = self._names(
			filters={"initiated_by": self.alice}, pending_action_by=self.bob
		)

		self.assertIn(both, names)
		self.assertNotIn(wrong_initiator, names)
		self.assertNotIn(wrong_assignee, names)
