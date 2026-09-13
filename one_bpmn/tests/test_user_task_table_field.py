# Copyright (c) 2026, one-fm and contributors
"""A User Task assigned to a table of users: everyone in it holds the task.

"Table Field" mode reads the users out of a child table on the context document
— Task's assignee table, a Department's approvers, a User Group's members — and
any one of them may action it. The engine has to fan that single resolved value
out: a ToDo each, a notification each, and a completion by any of them.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_user_task_table_field
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _extract_user_task_config
from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import assignment

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_TableField" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_table_field" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start_1" targetRef="Task_1" />
    <bpmn:userTask id="Task_1" name="Review Membership"
        spiffworkflow:assigneeMode="Table Field"
        spiffworkflow:targetDoctype="User Group"
        spiffworkflow:assigneeTableField="user_group_members"
        spiffworkflow:assigneeTableUserField="user"
        spiffworkflow:notifyAssignee="true"
        spiffworkflow:notifyAssigneeBody="PHA+UGxlYXNlIHJldmlldyB7eyBpbnN0YW5jZS5uYW1lIH19PC9wPg=="
        spiffworkflow:taskActions="Approve">
      <bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_1" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

USER_A = "_bpmn_table_a@example.com"
USER_B = "_bpmn_table_b@example.com"
OUTSIDER = "_bpmn_table_c@example.com"


def _user(email):
	if not frappe.db.exists("User", email):
		doc = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": "System User",
			"roles": [{"role": "System Manager"}],
		})
		doc.flags.no_welcome_mail = True
		doc.insert(ignore_permissions=True)
	return email


class TestUserTaskAssignedToATable(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email in (USER_A, USER_B, OUTSIDER):
			_user(email)

	def setUp(self):
		super().setUp()
		# log_error triggers an unrelated broken hook chain on this bench.
		patcher = patch.object(frappe, "log_error")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")

		self.group = frappe.get_doc({
			"doctype": "User Group",
			"__newname": f"_BPMN Table {frappe.generate_hash(length=6)}",
			"user_group_members": [{"user": USER_A}, {"user": USER_B}],
		}).insert(ignore_permissions=True)

	def _start(self):
		"""Run the flow up to the User Task and persist the instance."""
		extensions = _extract_user_task_config(_XML)
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(_XML, "proc_table_field")

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"test-{frappe.generate_hash(length=6)}",
			"status": "Active",
			"context_doctype": "User Group",
			"context_docname": self.group.name,
		})
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)

		instance._user_task_extensions = extensions
		instance._service_task_extensions = {}
		instance._script_task_extensions = {}

		wf = bpmn_engine.create_workflow(spec_dict, sp_specs, initial_data={})
		with patch.object(frappe, "enqueue"):
			instance._run_engine(wf)
			# The controller's own start order: run, then publish the tasks the
			# run stopped on. Assignment happens in the second step.
			instance._sync_active_tasks(wf)

		bpmn_engine.clean_doc_from_wf_data(wf)
		instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		instance.serialized_spec = json.dumps({
			"service_task_extensions": {},
			"user_task_extensions": extensions,
			"script_task_extensions": {},
		})
		instance.db_update()
		instance.update_children()
		return instance

	def _todos(self, status="Open"):
		return set(frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "User Group",
				"reference_name": self.group.name,
				"status": status,
			},
			pluck="allocated_to",
		))

	def test_the_whole_table_holds_the_task(self):
		instance = self._start()
		row = next(r for r in instance.active_tasks if r.status == "Waiting")

		self.assertEqual(row.task_name, "Review Membership")
		self.assertEqual(assignment.split_users(row.assigned_user), [USER_A, USER_B])

	def test_everyone_in_the_table_gets_their_own_todo(self):
		"""One ToDo per person, not one ToDo holding a comma-joined string —
		a ToDo belongs to a person and is what puts the task on their desk."""
		self._start()
		self.assertEqual(self._todos(), {USER_A, USER_B})

	def test_everyone_in_the_table_is_notified(self):
		"""Notify Assignee is a per-task opt-in, and the task belongs to all of
		them — so each member gets their own email, not just whoever is first."""
		fake_processor = types.ModuleType("one_fm.processor")
		fake_processor.sendemail = Mock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")

		with patch.dict(sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_processor}):
			self._start()

		recipients = {
			r
			for call in fake_processor.sendemail.call_args_list
			for r in call.kwargs["recipients"]
		}
		self.assertEqual(recipients, {USER_A, USER_B})

	def test_the_task_is_pending_for_each_member_and_nobody_else(self):
		from one_bpmn.api.instance_api import _instances_pending_on

		instance = self._start()

		self.assertIn(instance.name, _instances_pending_on(USER_A))
		self.assertIn(instance.name, _instances_pending_on(USER_B))
		self.assertNotIn(instance.name, _instances_pending_on(OUTSIDER))

	def test_any_member_can_complete_it(self):
		"""The second member, not the first: completion is a membership test,
		not a match against the head of the list."""
		from one_bpmn.api.instance_api import complete_task

		instance = self._start()
		task_id = next(r.task_id for r in instance.active_tasks if r.status == "Waiting")

		frappe.set_user(USER_B)
		with patch.object(frappe, "enqueue"):
			complete_task(instance.name, task_id, data=json.dumps({"action": "Approve"}))
		frappe.set_user("Administrator")

		instance.reload()
		self.assertFalse([r for r in instance.active_tasks if r.status == "Waiting"])
		# The other member's ToDo is closed too — the task is done for everyone.
		self.assertFalse(self._todos(status="Open"))

	def test_a_non_member_is_refused(self):
		from one_bpmn.api.instance_api import complete_task

		instance = self._start()
		task_id = next(r.task_id for r in instance.active_tasks if r.status == "Waiting")

		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			complete_task(instance.name, task_id, data=json.dumps({"action": "Approve"}))
		frappe.set_user("Administrator")
