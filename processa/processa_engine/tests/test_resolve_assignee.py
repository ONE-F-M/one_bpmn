# Copyright (c) 2026, one-fm and contributors
"""resolve_assignee takes the user task config as an argument and returns the relief pairs."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine import assignment


class TestResolveAssignee(FrappeTestCase):
	def test_the_assignee_and_relief_pairs_come_back_from_the_given_config(self):
		def on_leave(user, pairs):
			pairs.append((user, "reliever@example.com"))
			return "reliever@example.com"

		instance = frappe._dict(context_doctype="ToDo", context_docname="x", process_model="m")
		task = SimpleNamespace(task_spec=SimpleNamespace(bpmn_id="Task_1"))
		extensions = {"Task_1": {"assigneeMode": "User", "assigneeUser": "owner@example.com"}}
		with patch.object(assignment, "get_reliever_if_on_leave", side_effect=on_leave):
			result = assignment.resolve_assignee(instance, task, extensions)
		self.assertEqual(result, ("reliever@example.com", [("owner@example.com", "reliever@example.com")]))
