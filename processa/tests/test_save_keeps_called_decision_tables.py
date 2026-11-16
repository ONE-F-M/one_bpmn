"""Saving a map keeps the decision tables its Business Rule Tasks call and drops the rest."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import dmn
from processa.processa_engine.maps import saving

MODEL = "Called Decision Save Test Model"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_called_decision" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="called_decision_save" isExecutable="true">
    <bpmn:businessRuleTask id="pick_approver" name="Pick the approver" spiffworkflow:calledDecisionId="approver_table">
      <bpmn:extensionElements>
        <spiffworkflow:calledDecisionId>approver_table</spiffworkflow:calledDecisionId>
      </bpmn:extensionElements>
    </bpmn:businessRuleTask>
  </bpmn:process>
</bpmn:definitions>"""


def dmn_for(decision_id: str) -> str:
	return (
		'<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="d">'
		f'<decision id="{decision_id}" /></definitions>'
	)


class TestSaveKeepsCalledDecisionTables(FrappeTestCase):
	def setUp(self):
		frappe.delete_doc("BPMN Process Model", MODEL, force=True, ignore_missing=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = MODEL
		doc.title = MODEL
		doc.process_id = "called_decision_save"
		doc.bpmn_xml = XML
		doc.insert()

	def test_a_table_the_task_calls_survives_a_save(self):
		dmn.save_dmn_xml(MODEL, "approver_table", "Pick the approver", dmn_for("approver_table"))

		saving.save_model(MODEL, XML)

		self.assertEqual(dmn.get_dmn_xml(MODEL, "approver_table"), dmn_for("approver_table"))

	def test_a_table_nothing_names_is_dropped(self):
		dmn.save_dmn_xml(MODEL, "old_table", "Old", dmn_for("old_table"))

		saving.save_model(MODEL, XML)

		self.assertEqual(dmn.get_decision_list(MODEL), [])
