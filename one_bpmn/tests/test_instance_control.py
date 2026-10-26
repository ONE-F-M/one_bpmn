# Copyright (c) 2026, one-fm and contributors
"""Cancel, suspend, resume and retry-failed-step on a process instance, driven through real maps."""

import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import instance_control
from one_bpmn.api.compilation import compile_process_model
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import BPMNProcessInstance
from one_bpmn.tasks import _refresh_timer_tasks, process_timer_catch_events
from one_bpmn.tests.test_timer_sweep import TIMER_XML

SCRIPT = "_Test Instance Control Divide"

SCRIPT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_InstanceControl" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_InstanceControl" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="divide" />
    <bpmn:scriptTask id="divide" name="Divide" spiffworkflow:serverScript="{SCRIPT}">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="divide" targetRef="review" />
    <bpmn:userTask id="review" name="Review">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="review" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_3</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


SUBMIT_FIRST_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_InstanceControlSubmit" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_InstanceControlSubmit" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="submit" />
    <bpmn:userTask id="submit" name="Submit">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="submit" targetRef="divide" />
    <bpmn:scriptTask id="divide" name="Divide" spiffworkflow:serverScript="{SCRIPT}">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="divide" targetRef="review" />
    <bpmn:userTask id="review" name="Review">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:outgoing>Flow_4</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_4" sourceRef="review" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_4</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


def _instance(xml):
	suffix = frappe.generate_hash(length=6)
	process = frappe.get_doc(
		{
			"doctype": "Process",
			"process_name": f"instance-control-{suffix}",
			"description": "Instance control test",
			"process_owner": "Administrator",
		}
	).insert()
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": f"instance-control-model-{suffix}",
			"process_id": f"instance-control-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": xml,
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	compile_process_model(model.name)
	return frappe.get_doc({"doctype": "BPMN Process Instance", "process_model": model.name}).insert()


def _set_script(body):
	if frappe.db.exists("Server Script", SCRIPT):
		frappe.db.set_value("Server Script", SCRIPT, "script", body)
	else:
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT,
				"script_type": "API",
				"api_method": frappe.scrub(SCRIPT),
				"script": body,
			}
		).insert()


def _actions(instance_name, action):
	return frappe.db.count("BPMN Activity Log", {"instance": instance_name, "action": action})


class InstanceControlTestCase(FrappeTestCase):
	def setUp(self):
		# _record_runtime_failure commits; keep the fixtures inside the test transaction.
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)


class TestRetryFailedStep(InstanceControlTestCase):
	def _errored(self):
		_set_script('result["quotient"] = 1 / 0')
		instance = _instance(SCRIPT_XML)
		with self.assertRaises(frappe.ValidationError):
			instance.start()
		instance.reload()
		self.assertEqual(instance.status, "Errored")
		return instance

	def test_a_fixed_script_runs_and_the_instance_moves_on(self):
		instance = self._errored()
		instance.db_set("initiated_by", "Guest")
		_set_script('result["quotient"] = 1 / 1')

		instance_control.retry_failed_step(instance.name, reason="script fixed")

		instance.reload()
		self.assertEqual(instance.status, "Active")
		self.assertEqual(instance.initiated_by, "Guest")
		self.assertEqual(
			[row.task_name for row in instance.active_tasks if row.status == "Waiting"], ["Review"]
		)
		self.assertEqual(_actions(instance.name, "Retried"), 1)

	def test_a_still_broken_script_stays_errored_under_a_new_reference(self):
		instance = self._errored()
		before = _actions(instance.name, "Errored")

		with self.assertRaises(frappe.ValidationError):
			instance_control.retry_failed_step(instance.name)

		instance.reload()
		self.assertEqual(instance.status, "Errored")
		self.assertEqual(_actions(instance.name, "Errored"), before + 1)
		self.assertEqual(_actions(instance.name, "Retried"), 0)

	def test_a_failure_after_a_saved_step_returns_to_that_step(self):
		_set_script('result["quotient"] = 1 / 0')
		instance = _instance(SUBMIT_FIRST_XML)
		instance.start()
		submit = next(row.task_id for row in instance.active_tasks if row.status == "Waiting")
		with self.assertRaises(frappe.ValidationError):
			instance.advance(submit)
		instance.reload()
		self.assertEqual(instance.status, "Errored")
		self.assertTrue(instance.workflow_state)
		_set_script('result["quotient"] = 1 / 1')

		instance_control.retry_failed_step(instance.name, reason="script fixed")

		instance.reload()
		self.assertEqual(instance.status, "Active")
		waiting = [row for row in instance.active_tasks if row.status == "Waiting"]
		self.assertEqual([row.task_name for row in waiting], ["Submit"])
		instance.advance(waiting[0].task_id)
		instance.reload()
		self.assertEqual(
			[row.task_name for row in instance.active_tasks if row.status == "Waiting"], ["Review"]
		)

	def test_only_an_errored_instance_can_retry(self):
		_set_script('result["quotient"] = 1 / 1')
		instance = _instance(SCRIPT_XML)
		instance.start()
		with self.assertRaises(frappe.ValidationError):
			instance_control.retry_failed_step(instance.name)


class TestCancel(InstanceControlTestCase):
	def test_the_instance_and_its_waiting_tasks_are_cancelled(self):
		_set_script('result["quotient"] = 1 / 1')
		instance = _instance(SCRIPT_XML)
		instance.start()

		instance_control.cancel_instance(instance.name, reason="duplicate request")

		instance.reload()
		self.assertEqual(instance.status, "Cancelled")
		self.assertEqual({row.status for row in instance.active_tasks}, {"Cancelled"})
		log = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": instance.name, "action": "Cancelled"},
			fields=["user", "data"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].user, "Administrator")
		self.assertIn("duplicate request", log[0].data)

	def test_a_completed_instance_cannot_be_cancelled(self):
		instance = _instance(TIMER_XML)
		instance.db_set("status", "Completed")
		with self.assertRaises(frappe.ValidationError):
			instance_control.cancel_instance(instance.name, reason="too late")
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Completed")

	def test_a_reason_is_required(self):
		instance = _instance(TIMER_XML)
		instance.start()
		with self.assertRaises(frappe.ValidationError):
			instance_control.cancel_instance(instance.name, reason="  ")


class TestSuspendAndResume(InstanceControlTestCase):
	def test_a_suspended_instance_is_left_alone_until_resumed(self):
		instance = _instance(TIMER_XML)
		instance.start()
		instance_control.suspend_instance(instance.name, reason="investigating")
		instance.reload()
		self.assertEqual(instance.status, "Suspended")

		with self.assertRaises(frappe.ValidationError):
			instance.advance("wait_a_second")
		with self.assertRaises(frappe.ValidationError):
			instance.receive_message("Any Message")

		time.sleep(1.2)
		with patch("one_bpmn.tasks._refresh_timer_tasks") as sweep:
			process_timer_catch_events()
		self.assertNotIn(instance.name, [call.args[0] for call in sweep.call_args_list])

		instance_control.resume_instance(instance.name, reason="done")
		_refresh_timer_tasks(instance.name)
		instance.reload()
		self.assertEqual(instance.status, "Completed")

	def test_every_suspend_and_resume_is_logged(self):
		instance = _instance(TIMER_XML)
		instance.start()
		for _ in range(2):
			instance_control.suspend_instance(instance.name, reason="pause")
			instance_control.resume_instance(instance.name)
		self.assertEqual(_actions(instance.name, "Suspended"), 2)
		self.assertEqual(_actions(instance.name, "Resumed"), 2)

	def test_resume_queues_parked_ai_steps_again(self):
		instance = _instance(TIMER_XML)
		instance.start()
		instance_control.suspend_instance(instance.name, reason="pause")
		parked = [{"kind": "service_task", "task_id": "parked-task"}]
		with (
			patch.object(BPMNProcessInstance, "get_parked_ai_units", return_value=parked),
			patch("one_bpmn.api.instance_api.retry_ai_task") as retry,
		):
			instance_control.resume_instance(instance.name)
		retry.assert_called_once_with(instance.name, "parked-task", kind="service_task")

	def test_only_an_active_instance_is_suspended_and_only_a_suspended_one_resumed(self):
		instance = _instance(TIMER_XML)
		instance.start()
		with self.assertRaises(frappe.ValidationError):
			instance_control.resume_instance(instance.name)
		instance.db_set("status", "Errored")
		with self.assertRaises(frappe.ValidationError):
			instance_control.suspend_instance(instance.name, reason="pause")


class TestWhoMayRecover(InstanceControlTestCase):
	def setUp(self):
		super().setUp()
		email = "instance-control-employee@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Control", "send_welcome_email": 0}
			).insert()
		if not frappe.db.exists("Has Role", {"parent": email, "role": "Employee"}):
			# one_fm drops the Employee role from a user with no Employee record, so the row goes in directly.
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": email,
					"parenttype": "User",
					"parentfield": "roles",
					"role": "Employee",
				}
			).db_insert()
			frappe.clear_cache(user=email)
		self.employee = email

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_an_employee_with_write_on_instances_is_still_refused(self):
		instance = _instance(TIMER_XML)
		instance.start()
		self.assertTrue(frappe.has_permission("BPMN Process Instance", "write", user=self.employee))
		frappe.set_user(self.employee)
		for call in (
			lambda: instance_control.cancel_instance(instance.name, reason="x"),
			lambda: instance_control.suspend_instance(instance.name, reason="x"),
			lambda: instance_control.resume_instance(instance.name),
			lambda: instance_control.retry_failed_step(instance.name),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Active")
