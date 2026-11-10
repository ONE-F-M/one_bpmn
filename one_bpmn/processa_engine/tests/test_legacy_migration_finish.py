# Copyright (c) 2026, one-fm and contributors
"""finish() drives a Processa Legacy Migration map that waits for it to Completed or Failed."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.processa_engine import legacy_migration
from one_bpmn.processa_engine.instances.starting import start_process
from one_bpmn.tests.factories.legacy_migration_maps import DRAFT, DT, OLD, definitions, deploy


class TestLegacyMigrationFinishFlow(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for state in (DRAFT, "Running", "Failed", "Completed"):
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
				).insert()
		cls.old_map = deploy("PLM Fin Old", OLD)
		cls.new_map = deploy("PLM Fin New", OLD)
		cls.flow_map = deploy("PLM Fin Flow", cls._finish_flow_xml)

	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_finish_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_finish_test")

	@staticmethod
	def _finish_flow_xml(pid):
		"""The end of the Processa Legacy Migration map: Running, wait for the finish message, then Completed or Failed."""
		plm_dt = "Processa Legacy Migration"

		def state(node_id, workflow_state, incoming, outgoing):
			return (
				f'<bpmn:serviceTask id="{node_id}" name="Set {workflow_state}" spiffworkflow:serviceType="apply_workflow" '
				f'spiffworkflow:serviceTargetDoctype="{plm_dt}" spiffworkflow:workflowState="{workflow_state}" '
				f'spiffworkflow:docStatus="0"><bpmn:incoming>{incoming}</bpmn:incoming>'
				f"<bpmn:outgoing>{outgoing}</bpmn:outgoing></bpmn:serviceTask>"
			)

		body = (
			'<bpmn:startEvent id="Start_1" name="Start"><bpmn:outgoing>F0</bpmn:outgoing></bpmn:startEvent>'
			+ state("Task_running", "Running", "F0", "F1")
			+ '<bpmn:intermediateCatchEvent id="Catch_finished" name="Finished"><bpmn:incoming>F1</bpmn:incoming>'
			'<bpmn:outgoing>F2</bpmn:outgoing><bpmn:messageEventDefinition messageRef="Message_finished" />'
			"</bpmn:intermediateCatchEvent>"
			'<bpmn:exclusiveGateway id="Gw" name="Completed?" default="F4"><bpmn:incoming>F2</bpmn:incoming>'
			"<bpmn:outgoing>F3</bpmn:outgoing><bpmn:outgoing>F4</bpmn:outgoing></bpmn:exclusiveGateway>"
			+ state("Task_completed", "Completed", "F3", "F5")
			+ state("Task_failed", "Failed", "F4", "F6")
			+ '<bpmn:endEvent id="End_1" name="End"><bpmn:incoming>F5</bpmn:incoming></bpmn:endEvent>'
			'<bpmn:endEvent id="End_2" name="End Failed"><bpmn:incoming>F6</bpmn:incoming></bpmn:endEvent>'
			'<bpmn:sequenceFlow id="F0" sourceRef="Start_1" targetRef="Task_running" />'
			'<bpmn:sequenceFlow id="F1" sourceRef="Task_running" targetRef="Catch_finished" />'
			'<bpmn:sequenceFlow id="F2" sourceRef="Catch_finished" targetRef="Gw" />'
			'<bpmn:sequenceFlow id="F3" sourceRef="Gw" targetRef="Task_completed">'
			'<bpmn:conditionExpression>migration_status == "Completed"</bpmn:conditionExpression></bpmn:sequenceFlow>'
			'<bpmn:sequenceFlow id="F4" sourceRef="Gw" targetRef="Task_failed" />'
			'<bpmn:sequenceFlow id="F5" sourceRef="Task_completed" targetRef="End_1" />'
			'<bpmn:sequenceFlow id="F6" sourceRef="Task_failed" targetRef="End_2" />'
		)
		message = f'<bpmn:message id="Message_finished" name="{legacy_migration.FINISHED_MESSAGE}" />'
		return definitions(pid, body, message)

	def test_finish_moves_the_waiting_map_to_completed(self):
		self.assertEqual(self._run_to_finish(migrated=1), ("Completed", "Completed", 0))

	def test_finish_moves_the_waiting_map_to_failed(self):
		self.assertEqual(self._run_to_finish(migrated=0), ("Failed", "Failed", 0))

	def _run_to_finish(self, migrated):
		# Saving the PLM would otherwise start whichever PLM map is active on the site.
		with patch("one_bpmn.processa_engine.triggers.on_doc_event"):
			name = (
				frappe.get_doc(
					{
						"doctype": "Processa Legacy Migration",
						"from_model": self.old_map,
						"to_model": self.new_map,
						"target_doctype": DT,
						"status": "Queued",
						"state_map": [{"old_state": DRAFT, "new_state": DRAFT}],
					}
				)
				.insert()
				.name
			)
			start_process(self.flow_map, "Processa Legacy Migration", name)
			self.assertEqual(
				frappe.db.get_value("Processa Legacy Migration", name, "workflow_state"), "Running"
			)
			frappe.db.set_value(
				"Processa Legacy Migration",
				name,
				{
					"status": "Running",
					"total_records": 1,
					"migrated_count": migrated,
					"failed_count": 1 - migrated,
				},
			)
			legacy_migration.finish(name)
		return frappe.db.get_value(
			"Processa Legacy Migration", name, ["status", "workflow_state", "docstatus"]
		)
