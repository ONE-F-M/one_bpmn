# Copyright (c) 2026, one-fm and contributors
# A non-executable process model is marked Active or Inactive without being compiled.

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.deploy import activate_non_executable_model, deactivate_non_executable_model

PROCESS = "Non Executable Active Process"
MODEL_A = "Non Executable Active A"
MODEL_B = "Non Executable Active B"
OTHER = "Non Executable Active Other"


def _xml(process_id: str, executable: bool) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" isExecutable="{str(executable).lower()}">
    <bpmn:task id="t" name="Review" />
  </bpmn:process>
</bpmn:definitions>"""


class TestNonExecutableActive(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._models = []
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": "Non executable",
					"process_owner": "Administrator",
				}
			).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=1)
		frappe.delete_doc("Process", PROCESS, force=1, ignore_missing=True)
		frappe.db.commit()
		super().tearDown()

	def _model(self, name, process_id, executable=False, process=PROCESS, active=0):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"name": name,
				"title": name,
				"process_id": process_id,
				"process_name": process,
				"bpmn_xml": _xml(process_id, executable),
				"version": 1,
			}
		).insert()
		frappe.db.set_value("BPMN Process Model", name, "is_active", active)
		self._models.append(name)

	def _active(self, name):
		return frappe.db.get_value("BPMN Process Model", name, "is_active")

	def test_activating_deactivates_the_other_models_of_the_process(self):
		self._model(MODEL_A, "NEA_A", active=0)
		self._model(MODEL_B, "NEA_B", active=1)

		activate_non_executable_model(MODEL_A)

		self.assertEqual(self._active(MODEL_A), 1)
		self.assertEqual(self._active(MODEL_B), 0)

	def test_activating_leaves_other_processes_alone(self):
		self._model(MODEL_A, "NEA_A", active=0)
		self._model(OTHER, "NEA_OTHER", process=None, active=1)

		activate_non_executable_model(MODEL_A)

		self.assertEqual(self._active(OTHER), 1)

	def test_deactivating_marks_the_model_inactive(self):
		self._model(MODEL_A, "NEA_A", active=1)

		deactivate_non_executable_model(MODEL_A)

		self.assertEqual(self._active(MODEL_A), 0)

	def test_an_executable_model_is_refused(self):
		self._model(MODEL_A, "NEA_A", executable=True, active=0)
		self._model(MODEL_B, "NEA_B", executable=True, active=1)

		with self.assertRaises(frappe.ValidationError):
			activate_non_executable_model(MODEL_A)
		with self.assertRaises(frappe.ValidationError):
			deactivate_non_executable_model(MODEL_B)

		self.assertEqual(self._active(MODEL_A), 0)
		self.assertEqual(self._active(MODEL_B), 1)

	def test_a_user_without_write_permission_is_refused(self):
		self._model(MODEL_A, "NEA_A", active=0)

		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			activate_non_executable_model(MODEL_A)
		with self.assertRaises(frappe.PermissionError):
			deactivate_non_executable_model(MODEL_A)

		frappe.set_user("Administrator")
		self.assertEqual(self._active(MODEL_A), 0)
