# Copyright (c) 2026, one-fm and contributors
"""A User Task extended to a role lets every holder of that role act, from the document and from the instance page."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from processa.processa_engine import assignment
from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.compiler.extensions import extract_user_task_config
from processa.processa_engine.instances.listing import _instances_pending_on
from processa.processa_engine.instances.task_actions import _task_authorization
from processa.processa_engine.runtime.active_tasks import sync_active_tasks
from processa.processa_engine.runtime.engine_loop import run_engine

ROLE = "ZZ Extend Role"
ASSIGNEE = "_bpmn_extend_assignee@example.com"
HOLDER = "_bpmn_extend_holder@example.com"
OUTSIDER = "_bpmn_extend_outsider@example.com"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_ExtendRole" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_extend_role" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start_1" targetRef="Task_1" />
    <bpmn:userTask id="Task_1" name="Review"
        spiffworkflow:assigneeMode="User"
        spiffworkflow:assigneeUser="{assignee}"
        spiffworkflow:extendToRole="{role}"
        spiffworkflow:taskActions="Approve">
      <bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_1" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


def _user(email, roles):
	if not frappe.db.exists("User", email):
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": r} for r in roles],
			}
		)
		doc.insert()
	return email


class TestUserTaskExtendedToARole(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		_user(ASSIGNEE, ["System Manager"])
		_user(HOLDER, [ROLE])
		_user(OUTSIDER, [])

	def setUp(self):
		super().setUp()
		self.note = frappe.get_doc(
			{"doctype": "Note", "title": f"Extend {frappe.generate_hash(length=6)}"}
		).insert()

	def _start(self):
		xml = XML.format(assignee=ASSIGNEE, role=ROLE)
		extensions = extract_user_task_config(xml)
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(xml, "proc_extend_role")
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"Extend Role {frappe.generate_hash(length=6)}",
				"process_id": f"proc_extend_role_{frappe.generate_hash(length=6)}",
				"bpmn_xml": xml,
			}
		)
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.flags.skip_process_id_regeneration = True
		model.insert()
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": model.name,
				"process_id": model.process_id,
				"status": "Active",
				"context_doctype": "Note",
				"context_docname": self.note.name,
			}
		).insert()
		instance._user_task_extensions = extensions
		instance._service_task_extensions = {}
		instance._script_task_extensions = {}
		wf = bpmn_engine.create_workflow(spec_dict, sp_specs, initial_data={})
		with patch.object(frappe, "enqueue"):
			run_engine(instance, wf)
			sync_active_tasks(instance, wf)
		bpmn_engine.clean_doc_from_wf_data(wf)
		instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		instance.serialized_spec = json.dumps({"user_task_extensions": extensions})
		instance.db_update()
		instance.update_children()
		return instance

	def test_every_holder_of_the_role_lands_on_other_allowed_users(self):
		row = self._start().active_tasks[0]

		self.assertEqual(row.assigned_user, ASSIGNEE)
		self.assertIn(HOLDER, assignment.split_users(row.other_allowed_users))
		self.assertNotIn(OUTSIDER, assignment.split_users(row.other_allowed_users))

	def test_a_role_holder_may_act_and_an_outsider_may_not(self):
		instance = self._start()
		row = instance.active_tasks[0]

		self.assertIsNone(_task_authorization(instance, row, HOLDER)[0])
		self.assertIsNone(_task_authorization(instance, row, ASSIGNEE)[0])
		self.assertIsNotNone(_task_authorization(instance, row, OUTSIDER)[0])

	def test_the_instance_is_pending_for_the_role_holder(self):
		instance = self._start()

		self.assertIn(instance.name, _instances_pending_on(HOLDER))
		self.assertNotIn(instance.name, _instances_pending_on(OUTSIDER))

	def test_two_roles_give_one_sorted_list_without_repeats(self):
		users = assignment.users_in_roles(f"{ROLE}, {ROLE}")

		self.assertEqual(users.count(HOLDER), 1)
		self.assertEqual(assignment.users_in_roles(""), "")
