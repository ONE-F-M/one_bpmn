# Copyright (c) 2026, one-fm and contributors
"""save_process_model refuses a user without permission on BPMN Process Model."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.process_maps import save_process_model

MODEL = "Process Map Endpoints Test Model"
NEW_MODEL = "Process Map Endpoints New Model"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_map_endpoints" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="map_endpoints" isExecutable="true">
    <bpmn:startEvent id="s" />
  </bpmn:process>
</bpmn:definitions>"""


class TestSaveProcessModelPermission(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", MODEL):
			doc = frappe.new_doc("BPMN Process Model")
			doc.name = MODEL
			doc.title = MODEL
			doc.process_id = "map_endpoints"
			doc.bpmn_xml = XML
			doc.insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_user_without_write_permission_cannot_save_a_map(self):
		frappe.set_user("Guest")
		self.assertFalse(frappe.has_permission("BPMN Process Model", "write"))

		with self.assertRaises(frappe.PermissionError):
			save_process_model(MODEL, XML.replace('id="s"', 'id="changed"'))

		frappe.set_user("Administrator")
		self.assertNotIn('id="changed"', frappe.db.get_value("BPMN Process Model", MODEL, "bpmn_xml"))

	def test_a_user_without_create_permission_cannot_add_a_map(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			save_process_model(NEW_MODEL, XML)

		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("BPMN Process Model", NEW_MODEL))

	def test_a_writer_saves_the_map(self):
		result = save_process_model(MODEL, XML.replace('id="s"', 'id="saved"'))

		self.assertEqual(result["name"], MODEL)
		self.assertIn('id="saved"', frappe.db.get_value("BPMN Process Model", MODEL, "bpmn_xml"))
