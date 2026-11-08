# Copyright (c) 2026, one-fm and contributors
"""A user without read permission on a process model cannot see its versions."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import versions

MODEL = "Versions Permission Test Model"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_versions_perm" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="versions_perm" isExecutable="true">
    <bpmn:startEvent id="s" />
  </bpmn:process>
</bpmn:definitions>"""


class TestVersionsReadPermission(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", MODEL):
			doc = frappe.new_doc("BPMN Process Model")
			doc.name = MODEL
			doc.title = MODEL
			doc.process_id = "versions_perm"
			doc.bpmn_xml = XML
			doc.insert()
		self.marker = frappe.generate_hash(length=8)
		self.snapshot = versions.create_diagram_snapshot(MODEL, XML.replace('id="s"', f'id="{self.marker}"'), "named")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_reader_sees_the_versions(self):
		history = versions.get_edit_history(MODEL)

		self.assertEqual(history[0]["head"], self.snapshot)
		self.assertIn(f'id="{self.marker}"', versions.get_snapshot_xml(self.snapshot)["xml_content"])
		self.assertEqual(versions.get_diagram_versions(MODEL), [])

	def test_a_user_without_read_permission_gets_a_permission_error(self):
		frappe.set_user("Guest")
		self.assertFalse(frappe.has_permission("BPMN Process Model", "read"))

		for call in (
			lambda: versions.get_edit_history(MODEL),
			lambda: versions.get_diagram_versions(MODEL),
			lambda: versions.get_diagram_version_xml(MODEL, MODEL),
			lambda: versions.get_snapshot_xml(self.snapshot),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_the_unused_endpoints_are_gone(self):
		from one_bpmn.api import dmn

		self.assertFalse(hasattr(versions, "restore_script_version"))
		self.assertFalse(hasattr(dmn, "update_decision_name"))
