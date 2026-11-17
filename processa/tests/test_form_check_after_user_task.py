# Copyright (c) 2026, one-fm and contributors
"""A form check that fails in the step after a user task is shown to the user, and nothing of the press is kept.

These run the real engine: a compiled map, a ToDo as the document, and complete_task as the browser calls it.
A web request rolls back when it raises; each test does the same with a savepoint.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.deploy import compile_process_model
from processa.processa_engine.instances.starting import start_process
from processa.processa_engine.instances.task_actions import complete_task

MESSAGE = "Write ok in the description before approving."


def _map(process_id: str, script: str, trigger: str = "") -> str:
	start = f"""<bpmn:startEvent id="start"><bpmn:outgoing>f1</bpmn:outgoing>{trigger}</bpmn:startEvent>"""
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" isExecutable="true">
    {start}
    <bpmn:userTask id="approve" name="Approve" spiffworkflow:assigneeMode="User"
        spiffworkflow:assigneeUser="Administrator" spiffworkflow:targetDoctype="ToDo"
        spiffworkflow:taskActions='[{{"action":"Approve"}}]'>
      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:scriptTask id="check" name="Check" spiffworkflow:serverScript="{script}">
      <bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing>
      <bpmn:script>{script}</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:endEvent id="end"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="approve" />
    <bpmn:sequenceFlow id="f2" sourceRef="approve" targetRef="check" />
    <bpmn:sequenceFlow id="f3" sourceRef="check" targetRef="end" />
  </bpmn:process>
</bpmn:definitions>"""


class FormCheckCase(FrappeTestCase):
	def setUp(self):
		suffix = frappe.generate_hash(length=6)
		self.script = f"Form Check Probe {suffix}"
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"__newname": self.script,
				"script_type": "API",
				"api_method": f"form_check_probe_{suffix}",
				"script": (
					"todo = frappe.get_doc(context_doctype, context_docname)\n"
					"text = todo.description or ''\n"
					"if 'crash' in text:\n"
					"    result['n'] = int('crash')\n"
					"if 'ok' not in text:\n"
					f"    frappe.throw('{MESSAGE}')\n"
				),
			}
		).insert()
		self.model = self._model(f"Form Check Probe {suffix}", f"form_check_probe_{suffix}")

	def _model(self, title: str, process_id: str, trigger: str = "") -> str:
		model = frappe.new_doc("BPMN Process Model")
		model.update(
			{"title": title, "process_id": process_id, "version": 1, "bpmn_xml": _map(process_id, self.script, trigger)}
		)
		model.flags.skip_process_id_regeneration = True
		model.insert()
		compile_process_model(model.name)
		return model.name

	def _todo(self, description: str) -> str:
		return frappe.get_doc({"doctype": "ToDo", "description": description, "allocated_to": "Administrator"}).insert().name

	def _press(self, instance: str, rolls_back: bool = True):
		"""Press Approve as a request would: on an error everything the press wrote is rolled back.

		A real fault commits the halt before it raises, which ends the savepoint, so that case skips the rollback."""
		task_id = frappe.db.get_value("BPMN Active Task", {"parent": instance, "status": "Waiting"}, "task_id")
		frappe.db.savepoint("press")
		try:
			return complete_task(instance, task_id, data=json.dumps({"action": "Approve"}))
		except Exception:
			if rolls_back:
				frappe.db.rollback(save_point="press")
			raise

	def _state(self, instance: str) -> dict:
		return frappe.db.get_value(
			"BPMN Process Instance", instance, ["status", "engine_in_progress"], as_dict=True
		)


class TestAFormCheckAfterAUserTask(FormCheckCase):
	def test_the_press_shows_the_form_message_and_the_instance_stays_on_the_task(self):
		todo = self._todo("please approve")
		instance = start_process(self.model, "ToDo", todo)["instance"]

		with self.assertRaises(frappe.ValidationError) as caught:
			self._press(instance)

		self.assertIn(MESSAGE, str(caught.exception))
		self.assertEqual(self._state(instance), {"status": "Active", "engine_in_progress": 0})
		self.assertTrue(frappe.db.exists("BPMN Active Task", {"parent": instance, "status": "Waiting"}))

	def test_a_rejected_press_leaves_no_completed_row_in_the_activity_log(self):
		todo = self._todo("please approve")
		instance = start_process(self.model, "ToDo", todo)["instance"]

		with self.assertRaises(frappe.ValidationError):
			self._press(instance)

		self.assertFalse(
			frappe.db.exists("BPMN Activity Log", {"instance": instance, "task_name": "Approve", "action": "Completed"})
		)

	def test_after_the_fix_a_second_press_runs_the_step_and_completes(self):
		todo = self._todo("please approve")
		instance = start_process(self.model, "ToDo", todo)["instance"]
		with self.assertRaises(frappe.ValidationError):
			self._press(instance)

		frappe.db.set_value("ToDo", todo, "description", "ok, approve")
		self._press(instance)

		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance, "status"), "Completed")

	def test_a_real_fault_still_halts_the_instance_with_a_reference_id(self):
		todo = self._todo("crash")
		instance = start_process(self.model, "ToDo", todo)["instance"]

		with self.assertRaises(frappe.ValidationError) as caught:
			self._press(instance, rolls_back=False)

		self.assertIn("Reference ID", str(caught.exception))
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", instance, "status"), "Errored")


class TestAFormCheckWhenASaveStartsTheProcess(FormCheckCase):
	"""A map started by a ToDo save, whose first step is the check: the save itself is refused."""

	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=6)
		# Digits only, so the description never happens to contain the "ok" the check looks for.
		self.subject = f"form check start {int(frappe.utils.now_datetime().timestamp() * 1000)}"
		trigger = (
			'<bpmn:conditionalEventDefinition id="cond" spiffworkflow:triggerDoctype="ToDo" '
			'spiffworkflow:triggerType="After Insert" spiffworkflow:triggerFieldName="description" '
			f'spiffworkflow:triggerFieldValue="{self.subject}">'
			f'<bpmn:condition>description == "{self.subject}"</bpmn:condition>'
			"</bpmn:conditionalEventDefinition>"
		)
		process_id = f"form_check_start_{suffix}"
		xml = _map(process_id, self.script, trigger)
		# The check runs before any user task, so the save is what it refuses.
		xml = xml.replace('<bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="approve" />', '<bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="check" />')
		model = frappe.new_doc("BPMN Process Model")
		model.update({"title": f"Form Check Start {suffix}", "process_id": process_id, "version": 1, "bpmn_xml": xml})
		model.flags.skip_process_id_regeneration = True
		model.insert()
		compile_process_model(model.name)
		frappe.cache.delete_keys("bpmn")
		self.start_model = model.name

	def test_the_save_is_refused_with_the_form_message_and_no_instance_is_left_errored(self):
		frappe.db.savepoint("save")
		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.get_doc(
				{"doctype": "ToDo", "description": self.subject, "allocated_to": "Administrator"}
			).insert()
		frappe.db.rollback(save_point="save")

		self.assertIn(MESSAGE, str(caught.exception))
		self.assertFalse(
			frappe.db.exists("BPMN Process Instance", {"process_model": self.start_model, "status": "Errored"})
		)


class TestAFormCheckWhenASaveMovesTheProcessOn(FormCheckCase):
	"""A map waiting for the ToDo to be edited: the edit runs the check, and a failed check refuses the save."""

	def setUp(self):
		super().setUp()
		suffix = frappe.generate_hash(length=6)
		process_id = f"form_check_edit_{suffix}"
		xml = _map(process_id, self.script)
		xml = xml.replace(
			'<bpmn:userTask id="approve" name="Approve"',
			'<bpmn:intermediateCatchEvent id="approve" name="Edited"',
		).replace(
			"""      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:userTask>""",
			"""      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_edit" />
    </bpmn:intermediateCatchEvent>""",
		).replace(
			'<bpmn:process id=',
			'<bpmn:message id="Msg_edit" name="ToDo_Edit_Action" />\n  <bpmn:process id=',
		)
		model = frappe.new_doc("BPMN Process Model")
		model.update({"title": f"Form Check Edit {suffix}", "process_id": process_id, "version": 1, "bpmn_xml": xml})
		model.flags.skip_process_id_regeneration = True
		model.insert()
		compile_process_model(model.name)
		self.edit_model = model.name

	def test_an_edit_whose_step_fails_the_check_is_refused_and_the_instance_keeps_waiting(self):
		todo = self._todo("please approve")
		instance = start_process(self.edit_model, "ToDo", todo)["instance"]
		doc = frappe.get_doc("ToDo", todo)
		doc.description = "still please approve"
		# A fresh request: earlier saves in this test process already left their marks on these flags.
		frappe.flags._bpmn_message_sent = None
		frappe.flags._bpmn_instances_just_started = None

		frappe.db.savepoint("save")
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.save()
		frappe.db.rollback(save_point="save")

		self.assertIn(MESSAGE, str(caught.exception))
		self.assertEqual(self._state(instance), {"status": "Active", "engine_in_progress": 0})
		self.assertEqual(frappe.db.get_value("ToDo", todo, "description"), "please approve")
