# Copyright (c) 2026, one-fm and contributors
"""A DMN table saved for a Business Rule Task loads back and shows in the decision list."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import dmn

MODEL = "DMN Endpoints Test Model"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_dmn_endpoints" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="dmn_endpoints" isExecutable="true">
    <bpmn:businessRuleTask id="rule_1" />
  </bpmn:process>
</bpmn:definitions>"""
DMN = '<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="d"><decision id="rule_1" /></definitions>'


class TestDmnEndpoints(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", MODEL):
			doc = frappe.new_doc("BPMN Process Model")
			doc.name = MODEL
			doc.title = MODEL
			doc.process_id = "dmn_endpoints"
			doc.bpmn_xml = XML
			doc.insert()

	def test_a_saved_table_loads_and_is_listed(self):
		dmn.save_dmn_xml(MODEL, "rule_1", "Pick a rate", DMN)
		dmn.save_dmn_xml(MODEL, "rule_1", "Pick a rate", DMN.replace('id="d"', 'id="d2"'))

		self.assertIn('id="d2"', dmn.get_dmn_xml(MODEL, "rule_1"))
		self.assertEqual(dmn.get_decision_list(MODEL, "rate"), [{"decision_id": "rule_1", "decision_name": "Pick a rate"}])
		self.assertEqual(dmn.get_dmn_xml(MODEL, "missing"), "")

	def test_an_empty_table_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			dmn.save_dmn_xml(MODEL, "rule_1", "Pick a rate", "  ")
