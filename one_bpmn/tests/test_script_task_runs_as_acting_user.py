# Copyright (c) 2026, one-fm and contributors
"""A script task runs as the user who acted on the task before it, not as the user who started the instance.

Both production incidents of 2026-10-17 to 2026-10-19 failed the same way: an
approver completed a task, the script after it ran as the record's creator,
and the creator lacked the role or the User Permission the script needed.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

SCRIPT = "Record the user the script runs as"

MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_ActingUser" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_ActingUser" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_Act" />
    <bpmn:userTask id="Task_Act" name="Act"><bpmn:incoming>Flow_1</bpmn:incoming><bpmn:outgoing>Flow_2</bpmn:outgoing></bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Act" targetRef="Task_Script" />
    <bpmn:scriptTask id="Task_Script" name="Record user" spiffworkflow:serverScript="{script}"><bpmn:incoming>Flow_2</bpmn:incoming><bpmn:outgoing>Flow_3</bpmn:outgoing><bpmn:script>{script}</bpmn:script></bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_Script" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_3</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
""".replace("{script}", SCRIPT)


class TestScriptTaskRunsAsActingUser(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.creator = self._user("creator")
		self.approver = self._user("approver")
		if not frappe.db.exists("Server Script", SCRIPT):
			script = frappe.get_doc(
				{
					"doctype": "Server Script",
					"script_type": "API",
					"api_method": "record_the_user_the_script_runs_as",
					"script": 'result["ran_as"] = frappe.session.user\n',
				}
			)
			setattr(script, "__newname", SCRIPT)
			script.insert()

	def _user(self, label: str) -> str:
		email = f"{label}-{frappe.generate_hash(length=6)}@acting-user.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": label,
				"send_welcome_email": 0,
				"roles": [{"role": "System Manager"}],
			}
		).insert()
		return email

	def _started_instance(self):
		from one_bpmn.api.compilation import compile_process_model

		suffix = frappe.generate_hash(length=6)
		process = frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": f"acting-user-{suffix}",
				"description": "script run-as test",
				"process_owner": "Administrator",
			}
		).insert()
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"acting-user-model-{suffix}",
				"process_id": f"acting-user-{suffix}",
				"version": 1,
				"process_name": process.name,
				"bpmn_xml": MODEL_XML,
			}
		)
		model.flags.skip_editability_check = True
		model.insert()
		compile_process_model(model.name)

		frappe.set_user(self.creator)
		instance = frappe.get_doc({"doctype": "BPMN Process Instance", "process_model": model.name}).insert()
		instance.start(initial_data={})
		frappe.set_user("Administrator")
		return frappe.get_doc("BPMN Process Instance", instance.name)

	def _ran_as(self, instance) -> str:
		instance.reload()
		return json.loads(instance.workflow_state)["data"].get("ran_as")

	def test_script_after_a_user_task_runs_as_the_user_who_completed_it(self):
		instance = self._started_instance()
		task_id = next(row.task_id for row in instance.active_tasks if row.status == "Waiting")

		frappe.set_user(self.approver)
		instance.advance(task_id, {})

		self.assertEqual(self._ran_as(instance), self.approver)
