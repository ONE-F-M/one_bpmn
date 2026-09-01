# Copyright (c) 2026, one-fm and contributors
"""Notify Assignee fires per TASK, not once per person per instance.

Observed on the Software Development map: a developer completed Start Work,
Developer Actions and Add AI Feedback in turn — all three assigned to them via
``assignee_user``, two of them ticking Notify Assignee — and exactly one email
arrived, for the first.

Nothing errored. The notification lived inside ``add_frappe_assignment``, and
that is only called for a user who is not already assigned on the instance:

    for user, info in curr_assigned.items():
        if user not in prev_assigned:
            add_frappe_assignment(...)

A ToDo is deliberately kept open while its owner still has a Waiting row rather
than being closed and recreated per task, so from the second task onward the
call never happened — and the email went with it. Closing the ToDo would not
have helped: the guard is on ``prev_assigned``, not on the ToDo.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import (
	add_frappe_assignment,
	notify_task_assignee,
)

NOTIFY_CFG = {
	"notifyAssignee": "true",
	"notifyAssigneeBody": "<p>Task {{ instance.name }} is yours</p>",
}


def _instance(name="TEST-NOTIFY-PI"):
	inst = Mock()
	inst.name = name
	inst.context_doctype = "ToDo"
	inst.context_docname = "DOC-NOTIFY-1"
	inst.initiated_by = "Administrator"
	return inst


class TestNotifyAssigneePerTask(FrappeTestCase):
	def _patched_sendemail(self):
		"""Stand in for ``one_fm.processor.sendemail``.

		Imported locally by the sender and only falling back to
		``frappe.sendmail`` on ImportError, so the module is swapped rather
		than the attribute — the test then holds regardless of whether one_fm
		is installed.
		"""
		fake_proc = types.ModuleType("one_fm.processor")
		fake_proc.sendemail = Mock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		patcher = patch.dict(sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_proc})
		return patcher, fake_proc.sendemail

	def test_notifies_even_when_the_user_already_holds_an_open_todo(self):
		"""The regression. An open ToDo must not suppress the next task's email."""
		inst = _instance()
		patcher, sendemail = self._patched_sendemail()
		with patcher, patch.object(
			frappe.db, "exists", return_value="an-open-todo"
		):
			notify_task_assignee(inst, "dev@x.com", "Add AI Feedback & Labels", NOTIFY_CFG)
		self.assertTrue(
			sendemail.called,
			"an already-assigned user stopped being notified — the original defect",
		)

	def test_three_consecutive_tasks_for_one_person_send_three_emails(self):
		"""The Software Development path, in miniature."""
		inst = _instance()
		patcher, sendemail = self._patched_sendemail()
		with patcher, patch.object(
			frappe.db, "exists", return_value="an-open-todo"
		):
			for task in ("Start Work", "Developer Actions Work Item", "Add AI Feedback & Labels"):
				notify_task_assignee(inst, "dev@x.com", task, NOTIFY_CFG)
		self.assertEqual(sendemail.call_count, 3)

	def test_silent_when_the_task_does_not_ask_for_it(self):
		inst = _instance()
		patcher, sendemail = self._patched_sendemail()
		with patcher:
			notify_task_assignee(inst, "dev@x.com", "Accept/Reject Work Item", {})
			notify_task_assignee(inst, "dev@x.com", "Open Work Item", {"notifyAssignee": "false"})
			notify_task_assignee(inst, "dev@x.com", "Start Work", None)
		self.assertFalse(sendemail.called)

	def test_creating_a_todo_no_longer_sends_the_email(self):
		"""The two are separate now: assignment creates the ToDo and nothing else.

		Guards the other half — if the notification crept back into
		``add_frappe_assignment`` the first task of a run would send twice.
		"""
		inst = _instance()
		fake_todo = Mock()
		fake_todo.insert = Mock(return_value=fake_todo)
		fake_todo.name = "TODO-1"
		fake_ctx = Mock(doctype="ToDo", name="DOC-NOTIFY-1")

		def get_doc_side(*args, **kwargs):
			return fake_todo if args and isinstance(args[0], dict) else fake_ctx

		patcher, sendemail = self._patched_sendemail()
		with patcher, \
			patch.object(frappe.db, "exists", return_value=None), \
			patch.object(frappe.db, "set_value"), \
			patch.object(frappe, "get_doc", side_effect=get_doc_side), \
			patch.object(frappe, "has_permission", return_value=True), \
			patch.object(frappe, "get_system_settings", return_value=False), \
			patch.object(frappe, "get_cached_value", return_value=False), \
			patch("one_bpmn.email_builder.composer.compose_and_send_task_email"):
			add_frappe_assignment(inst, "dev@x.com", "Start Work", task_cfg=NOTIFY_CFG)

		self.assertFalse(
			sendemail.called,
			"add_frappe_assignment sent the notification again — it would now double up",
		)

	def test_missing_context_document_is_a_no_op(self):
		inst = _instance()
		inst.context_docname = None
		patcher, sendemail = self._patched_sendemail()
		with patcher:
			notify_task_assignee(inst, "dev@x.com", "Start Work", NOTIFY_CFG)
		self.assertFalse(sendemail.called)

	def test_a_failing_send_never_raises(self):
		"""A task must not be stranded because its announcement failed."""
		inst = _instance()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment._send_assignee_notification",
			side_effect=RuntimeError("smtp down"),
		), patch.object(frappe, "log_error") as logged:
			notify_task_assignee(inst, "dev@x.com", "Start Work", NOTIFY_CFG)
		self.assertTrue(logged.called)
