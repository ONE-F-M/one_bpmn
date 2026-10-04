# Copyright (c) 2026, one-fm and contributors
"""Who may complete a Waiting user task: the assignees, a super user, or an approved CTC holder, and nobody else."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import instance_api

INSTANCE = frappe._dict(context_doctype="Work Item", context_docname="TEST-CONTEXT-0001")


class TestTaskAuthorization(FrappeTestCase):
	def test_an_assignee_may_complete_the_task(self):
		self.assertIsNone(_refusal("mg@example.com", assigned_user="mg@example.com,ee@example.com"))

	def test_the_document_owner_may_not_complete_someone_elses_task(self):
		"""The creator of the document used to be let through; the task belongs to its assignee."""
		todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "owned by the non-assignee", "allocated_to": "Administrator"}
		).insert()
		frappe.db.set_value("ToDo", todo.name, "owner", "ee@example.com")
		instance = frappe._dict(context_doctype="ToDo", context_docname=todo.name)
		refusal = _refusal("ee@example.com", assigned_user="mg@example.com", instance=instance)
		self.assertIn("not authorized", refusal or "", "the document owner was let through")

	def test_a_super_user_may_complete_any_task(self):
		self.assertIsNone(_refusal("ee@example.com", assigned_user="mg@example.com", super_user=True))

	def test_an_unclaimed_role_task_is_for_the_role_members_only(self):
		self.assertIsNone(_refusal("ee@example.com", assigned_role="Reviewer", roles=["Reviewer"]))
		self.assertIn("Reviewer", _refusal("ee@example.com", assigned_role="Reviewer", roles=["Employee"]))


def _refusal(user, assigned_user="", assigned_role="", super_user=False, roles=(), instance=INSTANCE):
	row = frappe._dict(assigned_user=assigned_user, assigned_role=assigned_role)
	with patch.object(instance_api, "_is_bpmn_super_user", return_value=super_user), patch.object(
		frappe, "get_roles", return_value=list(roles)
	):
		return instance_api._task_authorization(instance, row, user)[0]
