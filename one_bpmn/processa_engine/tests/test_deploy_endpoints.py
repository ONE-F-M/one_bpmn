# Copyright (c) 2026, one-fm and contributors
"""Deploy refuses a user without write permission and a map with a prohibited shape."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.deploy import compile_process_model, disable_process_model

MODEL = "Deploy Endpoints Test Model"


def _xml(body: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_deploy_endpoints" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="deploy_endpoints" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    {body}
  </bpmn:process>
</bpmn:definitions>"""


PLAIN = _xml(
	'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="e" />'
	'<bpmn:endEvent id="e"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>'
)
WITH_MANUAL_TASK = _xml(
	'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="m1" />'
	'<bpmn:manualTask id="m1" name="Check"><bpmn:incoming>f1</bpmn:incoming>'
	"<bpmn:outgoing>f2</bpmn:outgoing></bpmn:manualTask>"
	'<bpmn:sequenceFlow id="f2" sourceRef="m1" targetRef="e" />'
	'<bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
)


class TestDeployEndpoints(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _model(self, xml: str):
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = MODEL
		doc.title = MODEL
		doc.process_id = "deploy_endpoints"
		doc.bpmn_xml = xml
		doc.version = 1
		doc.insert()
		return doc

	def test_a_user_without_write_permission_cannot_deploy(self):
		self._model(PLAIN)
		frappe.set_user("Guest")
		self.assertFalse(frappe.has_permission("BPMN Process Model", "write"))

		with self.assertRaises(frappe.PermissionError):
			compile_process_model(MODEL)

		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("BPMN Process Model", MODEL, "serialized_spec"))

	def test_a_user_without_write_permission_cannot_disable(self):
		self._model(PLAIN)
		compile_process_model(MODEL)
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			disable_process_model(MODEL)

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("BPMN Process Model", MODEL, "is_active"), 1)

	def test_a_writer_deploys_and_disables(self):
		self._model(PLAIN)

		result = compile_process_model(MODEL)

		self.assertTrue(result["success"])
		self.assertEqual(frappe.db.get_value("BPMN Process Model", MODEL, "is_active"), 1)
		self.assertEqual(disable_process_model(MODEL)["running_instances"], 0)
		self.assertEqual(frappe.db.get_value("BPMN Process Model", MODEL, "is_active"), 0)

	def test_a_prohibited_shape_is_refused_with_its_message(self):
		self._model(WITH_MANUAL_TASK)

		with self.assertRaises(frappe.ValidationError) as ctx:
			compile_process_model(MODEL)

		self.assertEqual(
			str(ctx.exception),
			"Prohibited shapes found - the following BPMN elements are not allowed in executable "
			'processes:\n\n• Manual Task "Check" (m1) is not allowed in executable processes. '
			"Use a User Task instead.",
		)
		self.assertFalse(frappe.db.get_value("BPMN Process Model", MODEL, "is_active"))
