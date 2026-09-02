# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""add_sandbox_tool_defs, tested against a synthetic diagram built to match
realistic bpmn-js-authored structure (a real startEvent/endEvent/DI section)
— the real "Dev Agent" diagram was never seen while writing this module (it
ships by export/import, not in this repo), so this is the closest available
substitute for "does this actually work against a real diagram's shape"."""

from __future__ import annotations

import json
import textwrap

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.dev_agent_sandbox_tools import (
	SANDBOX_TOOL_DEFS_ID,
	SANDBOX_TOOL_SPECS,
	SandboxToolDefsError,
	add_sandbox_tool_defs,
)
from one_bpmn.api.compilation import _extract_service_task_config, _resolve_sandbox_tool_shapes


def _diagram(with_connector=True, with_di=True) -> str:
	connector = (
		"""
    <bpmn:serviceTask id="ServiceTask_DevAgent" name="Dispatch to sandbox"
        spiffworkflow:serviceType="connector"
        spiffworkflow:connectorId="agent_sandbox"
        spiffworkflow:operation="dispatch"
        spiffworkflow:connectorParams="{&quot;target_app&quot;: &quot;{{ task_data.target_app }}&quot;}"
        spiffworkflow:resultVariable="sandbox_result">
      <bpmn:incoming>flow1</bpmn:incoming>
      <bpmn:outgoing>flow2</bpmn:outgoing>
    </bpmn:serviceTask>
"""
		if with_connector
		else """
    <bpmn:scriptTask id="unrelated_task" name="Something Else" spiffworkflow:serverScript="Noop">
      <bpmn:incoming>flow1</bpmn:incoming>
      <bpmn:outgoing>flow2</bpmn:outgoing>
    </bpmn:scriptTask>
"""
	)
	di = (
		"""
  <bpmndi:BPMNDiagram id="Diagram_1">
    <bpmndi:BPMNPlane id="Plane_1" bpmnElement="dev_agent_test_process">
      <bpmndi:BPMNShape id="start1_di" bpmnElement="start1">
        <dc:Bounds x="100" y="180" width="36" height="36"/>
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
"""
		if with_di
		else ""
	)
	return textwrap.dedent(f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="dev_agent_test_process" isExecutable="true">
    <bpmn:startEvent id="start1"><bpmn:outgoing>flow1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="flow1" sourceRef="start1" targetRef="{'ServiceTask_DevAgent' if with_connector else 'unrelated_task'}"/>
{connector}
    <bpmn:endEvent id="end1"><bpmn:incoming>flow2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="flow2" sourceRef="{'ServiceTask_DevAgent' if with_connector else 'unrelated_task'}" targetRef="end1"/>
  </bpmn:process>
{di}
</bpmn:definitions>
""")


def _make_process_model(name: str, bpmn_xml: str) -> frappe.Document:
	process = frappe.get_doc({
		"doctype": "Process",
		"process_name": f"_sbxtools-{frappe.generate_hash(length=6)}",
		"description": "add_sandbox_tool_defs test process",
		"process_owner": "Administrator",
	}).insert(ignore_permissions=True)
	suffix = frappe.generate_hash(length=6)
	return frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": name,
		"process_id": f"_sbxtools-{suffix}",
		"version": 1,
		"process_name": process.name,
		"bpmn_xml": bpmn_xml,
	}).insert(ignore_permissions=True)


class SandboxToolDefsCase(FrappeTestCase):
	def setUp(self):
		self.made_models = []
		self.made_processes = []

	def tearDown(self):
		for m in self.made_models:
			frappe.delete_doc("BPMN Process Model", m, force=True, ignore_permissions=True, ignore_missing=True)
		for p in self.made_processes:
			frappe.delete_doc("Process", p, force=True, ignore_permissions=True, ignore_missing=True)
		super().tearDown()

	def _model(self, **kwargs):
		name = f"_SandboxToolDefs Test {frappe.generate_hash(length=6)}"
		doc = _make_process_model(name, _diagram(**kwargs))
		self.made_models.append(doc.name)
		self.made_processes.append(doc.process_name)
		return doc.name


class TestNoOpCases(SandboxToolDefsCase):
	def test_no_process_model_is_a_clean_noop(self):
		result = add_sandbox_tool_defs("_no_such_process_model_at_all")
		self.assertFalse(result["applied"])

	def test_blank_diagram_is_a_clean_noop(self):
		name = f"_SandboxToolDefs Blank {frappe.generate_hash(length=6)}"
		doc = _make_process_model(name, "")
		self.made_models.append(doc.name)
		self.made_processes.append(doc.process_name)
		result = add_sandbox_tool_defs(doc.name)
		self.assertFalse(result["applied"])

	def test_already_present_is_idempotent_not_duplicated(self):
		model_name = self._model()
		first = add_sandbox_tool_defs(model_name)
		self.assertTrue(first["applied"])
		second = add_sandbox_tool_defs(model_name)
		self.assertFalse(second["applied"])
		xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
		self.assertEqual(xml.count(f'id="{SANDBOX_TOOL_DEFS_ID}"'), 1)


class TestMissingConnectorShape(SandboxToolDefsCase):
	def test_no_matching_connector_shape_raises_with_a_specific_reason(self):
		model_name = self._model(with_connector=False)
		with self.assertRaises(SandboxToolDefsError) as cm:
			add_sandbox_tool_defs(model_name)
		self.assertIn("agent_sandbox", str(cm.exception))
		self.assertIn("dispatch", str(cm.exception))

	def test_a_rejected_diagram_is_left_untouched(self):
		model_name = self._model(with_connector=False)
		original_xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
		with self.assertRaises(SandboxToolDefsError):
			add_sandbox_tool_defs(model_name)
		self.assertEqual(frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml"), original_xml)


class TestSuccessfulSplice(SandboxToolDefsCase):
	def test_applies_and_redeploys(self):
		model_name = self._model()
		result = add_sandbox_tool_defs(model_name)
		self.assertTrue(result["applied"])

		xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
		self.assertIn(f'id="{SANDBOX_TOOL_DEFS_ID}"', xml)
		self.assertIn('spiffworkflow:sandboxToolsAdhoc="sandbox_tool_defs"', xml)
		# The connector shape's existing attributes must survive untouched.
		self.assertIn('spiffworkflow:connectorId="agent_sandbox"', xml)
		self.assertIn('spiffworkflow:resultVariable="sandbox_result"', xml)
		# DI shape for the new sub-process was added too, not just the logical XML.
		self.assertIn(f'bpmnElement="{SANDBOX_TOOL_DEFS_ID}"', xml)
		for spec in SANDBOX_TOOL_SPECS:
			self.assertIn(f'id="{spec["name"]}"', xml)

	def test_shapes_use_mixed_script_and_service_task_styling(self):
		"""Matches the real Orchestrator Agent's own convention (Script Tasks
		with a real serverScript+<bpmn:script>, Service Tasks with a real
		connectorId/operation) rather than one uniform generic shape — this
		is specifically what the user flagged as wrong in the live diagram
		the first time."""
		model_name = self._model()
		add_sandbox_tool_defs(model_name)
		xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")

		script_tools = [s for s in SANDBOX_TOOL_SPECS if s["shape"] == "script"]
		service_tools = [s for s in SANDBOX_TOOL_SPECS if s["shape"] == "service"]
		self.assertTrue(script_tools and service_tools, "fixture should exercise both styles")

		for spec in script_tools:
			self.assertIn(f'<bpmn:scriptTask id="{spec["name"]}"', xml)
			self.assertIn(f'spiffworkflow:serverScript="{spec["server_script"]}"', xml)
			self.assertIn("<bpmn:script>pass</bpmn:script>", xml)
		for spec in service_tools:
			self.assertIn(f'<bpmn:serviceTask id="{spec["name"]}"', xml)
			self.assertIn(f'spiffworkflow:operation="{spec["operation"]}"', xml)
		# Every tool has its own human-readable name, distinct from its id —
		# matching wi_comment's name="Record a comment" style, not a bare
		# repeat of the id as the display name.
		for spec in SANDBOX_TOOL_SPECS:
			self.assertIn(f'name="{spec["label"]}"', xml)

	def test_the_serialized_spec_actually_carries_sandbox_tool_shapes(self):
		"""Not just XML text — confirms compile_process_model's own
		extraction (_resolve_sandbox_tool_shapes) picks up what was spliced
		in, the same check a real dispatch_to_sandbox call depends on."""
		model_name = self._model()
		add_sandbox_tool_defs(model_name)

		xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
		svc = _extract_service_task_config(xml)
		_resolve_sandbox_tool_shapes(xml, svc)
		shapes = json.loads(svc["ServiceTask_DevAgent"]["sandboxToolShapes"])
		names = {s["bpmn_id"] for s in shapes}
		self.assertEqual(names, {spec["name"] for spec in SANDBOX_TOOL_SPECS})

		open_pr = next(s for s in shapes if s["bpmn_id"] == "open_pull_request")
		self.assertIn("summary", open_pr["parameters"])
		self.assertEqual(open_pr["required"], ["summary"])

	def test_other_diagram_content_is_undisturbed(self):
		model_name = self._model()
		add_sandbox_tool_defs(model_name)
		xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
		self.assertIn('<bpmn:startEvent id="start1">', xml)
		self.assertIn('<bpmn:endEvent id="end1">', xml)
		self.assertIn('bpmnElement="start1"', xml)  # original DI shape untouched
