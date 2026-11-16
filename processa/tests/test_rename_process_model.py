# Copyright (c) 2026, one-fm and contributors
"""Renaming a process map reports an overlapping rename instead of failing with a 500."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.maps.saving import rename_model

MODEL = "Rename Test Model"
RENAMED = "Rename Test Model Renamed"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_rename_test" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="rename_test" isExecutable="true">
    <bpmn:startEvent id="s" />
  </bpmn:process>
</bpmn:definitions>"""


class TestRenameProcessModel(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for name in (MODEL, RENAMED):
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=True)

		doc = frappe.new_doc("BPMN Process Model")
		doc.name = MODEL
		doc.title = MODEL
		doc.process_id = "rename_test"
		doc.bpmn_xml = XML
		doc.insert()

	def test_an_overlapping_rename_gives_a_clear_error(self):
		with patch("frappe.rename_doc", side_effect=frappe.QueryDeadlockError):
			with self.assertRaises(frappe.ValidationError) as ctx:
				rename_model(MODEL, RENAMED)

		self.assertIn("already being renamed", str(ctx.exception))

	def test_a_rename_returns_the_new_name_and_title(self):
		result = rename_model(MODEL, RENAMED)

		self.assertEqual(result["name"], RENAMED)
		self.assertEqual(result["model_name"], RENAMED)
		self.assertTrue(frappe.db.exists("BPMN Process Model", RENAMED))
		self.assertFalse(frappe.db.exists("BPMN Process Model", MODEL))
